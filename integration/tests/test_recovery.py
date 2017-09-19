import time

import pytest
import requests
from dcos.errors import DCOSException, DCOSAuthenticationException, DCOSHTTPException

import dcos
import shakedown
from tests.command import (
    cassandra_api_url,
    check_health,
    get_cassandra_config,
    marathon_api_url,
    unit_health_url,
    request,
    spin,
    unset_ssl_verification,
    install,
    uninstall,
)
from tests.defaults import DEFAULT_NODE_COUNT, PACKAGE_NAME, TASK_RUNNING_STATE
from . import infinity_commons

HEALTH_WAIT_TIME = 300


def bump_cpu_count_config(cpu_change=0.1):
    config = get_cassandra_config()
    config['env']['CASSANDRA_CPUS'] = str(
        float(config['env']['CASSANDRA_CPUS']) + cpu_change
    )
    response = request(
        dcos.http.put,
        marathon_api_url('apps/' + PACKAGE_NAME),
        json=config,
        is_success=request_success
    )

    return response


counter = 0


def get_and_verify_plan(predicate=lambda r: True, assert_success=True):
    global counter

    def fn():
        return dcos.http.get(cassandra_api_url('plan'), is_success=request_success)

    def success_predicate(result):
        global counter
        message = 'Request to /plan failed'

        try:
            body = result.json()
        except Exception:
            return False, message

        if counter < 3:
            counter += 1

        if predicate(body):
            counter = 0

        return predicate(body), message

    return spin(fn, success_predicate, wait_time=HEALTH_WAIT_TIME, assert_success=assert_success).json()


def request_success(status_code):
    return 200 <= status_code < 300 or 500 <= status_code <= 503 or status_code == 409 or status_code == 401


def get_node_host():
    def fn():
        try:
            return shakedown.get_service_ips(PACKAGE_NAME)
        except (IndexError, DCOSHTTPException):
            return set()

    def success_predicate(result):
        return len(result) == DEFAULT_NODE_COUNT, 'Nodes failed to return'

    return spin(fn, success_predicate).pop()


def get_scheduler_host():
    return shakedown.get_service_ips('marathon').pop()


def kill_task_with_pattern(pattern, host=None):
    command = (
        "sudo kill -9 "
        "$(ps ax | grep {} | grep -v grep | tr -s ' ' | sed 's/^ *//g' | "
        "cut -d ' ' -f 1)".format(pattern)
    )
    if host is None:
        result = shakedown.run_command_on_master(command)
    else:
        result = shakedown.run_command_on_agent(host, command)

    if not result:
        raise RuntimeError(
            'Failed to kill task with pattern "{}"'.format(pattern)
        )


def run_cleanup():
    payload = {'nodes': ['*']}
    request(
        dcos.http.put,
        cassandra_api_url('cleanup/start'),
        json=payload,
        is_success=request_success
    )


def run_planned_operation(operation, failure=lambda: None, recovery=lambda: None):
    plan = get_and_verify_plan()
    print("Running planned operation")
    operation()
    get_and_verify_plan(
        lambda p: (
            plan['phases'][1]['id'] != p['phases'][1]['id'] or
            len(plan['phases']) < len(p['phases']) or
            p['status'] == infinity_commons.PlanState.IN_PROGRESS.value
        )
    )
    print("Run failure operation")
    failure()
    print("Run recovery operation")
    recovery()
    print("Verify plan after failure")
    get_and_verify_plan(lambda p: p['status'] == infinity_commons.PlanState.COMPLETE.value)


def run_repair():
    payload = {'nodes': ['*']}
    request(
        dcos.http.put,
        cassandra_api_url('repair/start'),
        json=payload,
        is_success=request_success
    )


def _block_on_adminrouter(master_ip):
    headers = {'Authorization': "token={}".format(shakedown.dcos_acs_token())}
    metadata_url = "http://{}/metadata".format(master_ip)

    def get_metadata():
        response = requests.get(metadata_url, headers=headers)
        return response

    def success(response):
        error_message = "Failed to parse json"
        try:
            is_healthy = response.json()['PUBLIC_IPV4'] == master_ip
            return is_healthy, "Master is not healthy yet"
        except Exception:
            return False, error_message

    spin(get_metadata, success, HEALTH_WAIT_TIME)
    print("Master is up again.  Master IP: {}".format(master_ip))


def verify_leader_changed(old_leader_ip):

    def fn():
        try:
            return shakedown.master_leader_ip()
        except DCOSAuthenticationException:
            print("Got exception while fetching leader")
        return old_leader_ip

    def success_predicate(new_leader_ip):
        is_success = old_leader_ip != new_leader_ip
        return is_success, "Leader has not changed"

    result = spin(fn, success_predicate)
    print("Leader has changed to {}".format(result))


# Check if mesos agent / spartan is not running. Restart spartan to see if it is fixed
def recover_host_from_partitioning(host):
    # if is_dns_healthy_for_node(host):
    print("Restarting erlang and mesos on {}".format(host))
    restart_erlang_on_host(host)
    shakedown.restart_agent(host)


def is_dns_healthy_for_node(host):
    unit_and_node = "dcos-spartan.service/nodes/{}".format(host)
    health_check_url = unit_health_url(unit_and_node)
    try:
        response = dcos.http.get(health_check_url)
        return response.json()['health'] == 0
    except DCOSException:
        print("DNS call not responding")
    return False


def restart_erlang_on_host(host):
    command = "sudo systemctl restart dcos-epmd.service"
    print("Restarting erlang daemon")
    result = shakedown.run_command_on_agent(host, command)
    if not result:
        raise RuntimeError(
            'Failed to run command {} on {}'.format(command, host)
        )


# Restart mesos agent if service is stuck or not running on some nodes
def recover_failed_agents(hosts):
    tasks = check_health(wait_time=HEALTH_WAIT_TIME, assert_success=False)
    failed_hosts = find_failed_hosts(hosts, tasks)
    for h in failed_hosts:
        print("Restarting mesos agent on {}".format(h))
        shakedown.restart_agent(h)


def find_failed_hosts(hosts, tasks):
    failed_hosts = set(hosts)
    for t in tasks:
        if t['state'] == TASK_RUNNING_STATE:
            host = t['labels'][2]['value']
            failed_hosts.discard(host)
    return failed_hosts


def recover_agents(hosts):
    get_and_verify_plan(lambda p: p['status'] == infinity_commons.PlanState.COMPLETE.value, assert_success=False)
    for h in hosts:
        print("Restarting mesos agent on {}".format(h))
        shakedown.restart_agent(h)


def setup_module():
    unset_ssl_verification()
    uninstall()
    install()
    check_health()


def teardown_module():
    uninstall()


@pytest.mark.recovery
def test_kill_task_in_node():
    kill_task_with_pattern('CassandraDaemon', get_node_host())

    check_health()


@pytest.mark.recovery
def test_kill_all_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    for host in hosts:
        kill_task_with_pattern('CassandraDaemon', host)

    recover_failed_agents(hosts)
    check_health()


@pytest.mark.recovery
def test_scheduler_died():
    kill_task_with_pattern('cassandra.scheduler.Main', get_scheduler_host())

    check_health()


@pytest.mark.recovery
def test_executor_killed():
    host = get_node_host()
    kill_task_with_pattern('cassandra.executor.Main', host)

    recover_failed_agents([host])
    check_health()


@pytest.mark.recovery
def test_all_executors_killed():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    for host in hosts:
        kill_task_with_pattern('cassandra.executor.Main', host)

    recover_failed_agents(hosts)
    check_health()


@pytest.mark.recovery
def test_master_killed_block_on_admin_router():
    master_leader_ip = shakedown.master_leader_ip()
    kill_task_with_pattern('mesos-master', master_leader_ip)

    verify_leader_changed(master_leader_ip)
    check_health()


@pytest.mark.recovery
def test_zk_killed_recovery():
    master_leader_ip = shakedown.master_leader_ip()
    kill_task_with_pattern('zookeeper', master_leader_ip)

    _block_on_adminrouter(master_leader_ip)
    check_health()


@pytest.mark.recovery
def test_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    kill_task_with_pattern('zookeeper', master_leader_ip)

    verify_leader_changed(master_leader_ip)
    check_health()


@pytest.mark.recovery
def test_partition():
    host = get_node_host()

    shakedown.partition_agent(host)
    time.sleep(20)
    shakedown.reconnect_agent(host)
    recover_host_from_partitioning(host)

    check_health()


@pytest.mark.recovery
def test_partition_master_both_ways():
    master_leader_ip = shakedown.master_leader_ip()
    shakedown.partition_master(master_leader_ip)
    time.sleep(20)
    shakedown.reconnect_master(master_leader_ip)

    check_health()


@pytest.mark.recovery
def test_partition_master_incoming():
    master_leader_ip = shakedown.master_leader_ip()
    shakedown.partition_master(master_leader_ip, incoming=True, outgoing=False)
    time.sleep(20)
    shakedown.reconnect_master(master_leader_ip)

    check_health()


@pytest.mark.recovery
def test_partition_master_outgoing():
    master_leader_ip = shakedown.master_leader_ip()
    shakedown.partition_master(master_leader_ip, incoming=False, outgoing=True)
    time.sleep(20)
    shakedown.reconnect_master(master_leader_ip)

    check_health()


@pytest.mark.recovery
def test_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    for host in hosts:
        shakedown.partition_agent(host)
    time.sleep(20)
    for host in hosts:
        shakedown.reconnect_agent(host)
    for host in hosts:
        recover_host_from_partitioning(host)

    check_health()


@pytest.mark.recovery
def test_config_update_then_kill_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    host = get_node_host()

    run_planned_operation(
        bump_cpu_count_config,
        lambda: kill_task_with_pattern('CassandraDaemon', host),
        lambda: recover_failed_agents(hosts)
    )
    check_health()


@pytest.mark.recovery
def test_config_update_then_kill_all_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    run_planned_operation(
        lambda: bump_cpu_count_config(-0.1),
        lambda: [kill_task_with_pattern('CassandraDaemon', h) for h in hosts],
        lambda: recover_failed_agents(hosts)
    )
    check_health()


@pytest.mark.recovery
def test_config_update_then_scheduler_died():
    host = get_scheduler_host()

    run_planned_operation(
        bump_cpu_count_config,
        lambda: kill_task_with_pattern('cassandra.scheduler.Main', host)
    )

    check_health()


@pytest.mark.recovery
def test_config_update_then_executor_killed():
    host = get_node_host()

    run_planned_operation(
        lambda: bump_cpu_count_config(-0.1),
        lambda: kill_task_with_pattern('cassandra.executor.Main', host),
        lambda: recover_failed_agents([host])
    )
    check_health()


@pytest.mark.recovery
def test_config_update_then_all_executors_killed():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    run_planned_operation(
        bump_cpu_count_config,
        lambda: [kill_task_with_pattern('cassandra.executor.Main', h) for h in hosts],
        lambda: recover_failed_agents(hosts)
    )
    check_health()


@pytest.mark.recovery
def test_config_update_then_master_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        lambda: bump_cpu_count_config(-0.1), lambda: kill_task_with_pattern('mesos-master', master_leader_ip)
    )
    verify_leader_changed(master_leader_ip)
    check_health()


@pytest.mark.recovery
def test_config_update_then_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        bump_cpu_count_config,
        lambda: kill_task_with_pattern('zookeeper', master_leader_ip),
        lambda: verify_leader_changed(master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_config_update_then_partition():
    host = get_node_host()

    def partition():
        shakedown.partition_agent(host)
        time.sleep(20)
        shakedown.reconnect_agent(host)

    run_planned_operation(
        lambda: bump_cpu_count_config(-0.1), partition, lambda: recover_host_from_partitioning(host))

    check_health()


@pytest.mark.recovery
def test_config_update_then_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    def partition():
        for host in hosts:
            shakedown.partition_agent(host)
        time.sleep(20)
        for host in hosts:
            shakedown.reconnect_agent(host)

    def recovery():
        for host in hosts:
            recover_host_from_partitioning(host)

    run_planned_operation(bump_cpu_count_config, partition, recovery)
    check_health()


@pytest.mark.recovery
def test_cleanup_then_kill_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    host = get_node_host()

    run_planned_operation(
        run_cleanup,
        lambda: kill_task_with_pattern('CassandraDaemon', host),
        lambda: recover_failed_agents(hosts)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_kill_all_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    run_planned_operation(
        run_cleanup,
        lambda: [kill_task_with_pattern('CassandraDaemon', h) for h in hosts],
        lambda: recover_failed_agents(hosts)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_scheduler_died():
    host = get_scheduler_host()
    run_planned_operation(run_cleanup, lambda: kill_task_with_pattern('cassandra.scheduler.Main', host))

    check_health()


@pytest.mark.recovery
def test_cleanup_then_executor_killed():
    host = get_node_host()

    run_planned_operation(
        run_cleanup,
        lambda: kill_task_with_pattern('cassandra.executor.Main', host),
        lambda: recover_failed_agents([host])
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_all_executors_killed():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    run_planned_operation(
        run_cleanup,
        lambda: [kill_task_with_pattern('cassandra.executor.Main', h) for h in hosts],
        lambda: recover_failed_agents(hosts)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_master_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(run_cleanup, lambda: kill_task_with_pattern('mesos-master', master_leader_ip))

    verify_leader_changed(master_leader_ip)
    check_health()


@pytest.mark.recovery
def test_cleanup_then_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        run_cleanup,
        lambda: kill_task_with_pattern('zookeeper', master_leader_ip),
        lambda: verify_leader_changed(master_leader_ip))

    check_health()


@pytest.mark.recovery
def test_cleanup_then_partition():
    host = get_node_host()

    def partition():
        shakedown.partition_agent(host)
        time.sleep(20)
        shakedown.reconnect_agent(host)

    run_planned_operation(run_cleanup, partition, lambda: recover_host_from_partitioning(host))

    check_health()


@pytest.mark.recovery
def test_cleanup_then_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    def partition():
        for host in hosts:
            shakedown.partition_agent(host)
        time.sleep(20)
        for host in hosts:
            shakedown.reconnect_agent(host)

    def recovery():
        for host in hosts:
            recover_host_from_partitioning(host)

    run_planned_operation(run_cleanup, partition, recovery)
    check_health()


@pytest.mark.recovery
def test_repair_then_kill_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    host = get_node_host()

    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('CassandraDaemon', host),
        lambda: recover_failed_agents(hosts)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_kill_all_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    run_planned_operation(
        run_repair,
        lambda: [kill_task_with_pattern('CassandraDaemon', h) for h in hosts],
        lambda: recover_failed_agents(hosts)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_scheduler_died():
    host = get_scheduler_host()
    run_planned_operation(run_repair, lambda: kill_task_with_pattern('cassandra.scheduler.Main', host))

    check_health()


@pytest.mark.recovery
def test_repair_then_executor_killed():
    host = get_node_host()

    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('cassandra.executor.Main', host),
        lambda: recover_failed_agents([host])
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_all_executors_killed():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    run_planned_operation(
        run_repair,
        lambda: [kill_task_with_pattern('cassandra.executor.Main', h) for h in hosts],
        lambda: recover_failed_agents(hosts)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_master_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(run_repair, lambda: kill_task_with_pattern('mesos-master', master_leader_ip))

    verify_leader_changed(master_leader_ip)
    check_health()


@pytest.mark.recovery
def test_repair_then_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('zookeeper', master_leader_ip),
        lambda: verify_leader_changed(master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_partition():
    host = get_node_host()

    def partition():
        shakedown.partition_agent(host)
        time.sleep(20)
        shakedown.reconnect_agent(host)

    run_planned_operation(run_repair, partition, lambda: recover_host_from_partitioning(host))

    check_health()


@pytest.mark.recovery
def test_repair_then_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    def partition():
        for host in hosts:
            shakedown.partition_agent(host)
        time.sleep(20)
        for host in hosts:
            shakedown.reconnect_agent(host)

    def recovery():
        for host in hosts:
            recover_host_from_partitioning(host)

    run_planned_operation(run_repair, partition, recovery)

    check_health()
