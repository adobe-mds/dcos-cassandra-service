import dcos
import pytest
import shakedown
import time

from requests.exceptions import ConnectionError

from dcos.errors import DCOSException

from tests.command import (
    cassandra_api_url,
    check_health,
    get_cassandra_config,
    install,
    exhibitor_api_url,
    marathon_api_url,
    request,
    spin,
    uninstall,
    unset_ssl_verification,
)
from tests.defaults import DEFAULT_NODE_COUNT, PACKAGE_NAME
from . import infinity_commons


def bump_cpu_count_config():
    config = get_cassandra_config()
    config['env']['CASSANDRA_CPUS'] = str(
        float(config['env']['CASSANDRA_CPUS']) + 0.1
    )

    print("Bump CPU config")
    print(marathon_api_url('apps/'+PACKAGE_NAME))
    plan = dcos.http.get(cassandra_api_url('plan'), is_success=allow_incomplete_plan)
    print(plan.json())
    response =  request(
        dcos.http.put,
        marathon_api_url('apps/' + PACKAGE_NAME),
        json=config
    )
    print(response)
    print(response.text)
    return response


counter = 0
def get_and_verify_plan(predicate=lambda r: True):
    global counter

    def fn():
        return dcos.http.get(cassandra_api_url('plan'), is_success=allow_incomplete_plan)

    def success_predicate(result):
        global counter
        message = 'Request to /plan failed'

        try:
            body = result.json()
        except Exception as e:
            print(e)
            return False, message

        if counter < 3:
            counter += 1

        if predicate(body): counter = 0

        return predicate(body), message

    return spin(fn, success_predicate).json()


def allow_incomplete_plan(status_code):
    return 200 <= status_code < 300 or status_code == 503 or status_code == 502 or status_code == 500 or status_code == 409


def get_node_host():
    def fn():
        try:
            return shakedown.get_service_ips(PACKAGE_NAME)
        except IndexError:
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
    )


def run_planned_operation(operation, failure=lambda: None):
    plan = get_and_verify_plan()
    print("Running operation")
    operation()
    print("Verify plan after operation")
    next_plan = get_and_verify_plan(
        lambda p: (
            plan['phases'][1]['id'] != p['phases'][1]['id'] or
            len(plan['phases']) < len(p['phases']) or
            p['status'] == infinity_commons.PlanState.IN_PROGRESS.value
        )
    )
    print("Run failure operation")
    failure()
    print("Verify plan after failure")
    completed_plan = get_and_verify_plan(lambda p: p['status'] == infinity_commons.PlanState.COMPLETE.value)


def run_repair():
    payload = {'nodes': ['*']}
    request(
        dcos.http.put,
        cassandra_api_url('repair/start'),
        json=payload,
    )


def _block_on_adminrouter():
    def get_master_ip():
        return shakedown.master_ip()

    def is_up(ip):
        return ip, "Failed to fetch master ip"

    # wait for adminrouter to recover
    print("Ensuring adminrouter is up...")
    ip = spin(get_master_ip, is_up)
    print("Adminrouter is up.  Master IP: {}".format(ip))


def _block_on_adminrouter_new(master_ip):
    def get_node_health(master_ip):
        response = None
        try:
            response = dcos.http.get("http://" + master_ip + "/metadata")
        except DCOSException as e:
            print("Master IP {} not accessible: ".format(master_ip))
        return response

    def success(response):
        error_message = "Failed to parse json"
        try:
            body = response.json()
        except Exception as e:
            print(e)
            return False, error_message

        is_healthy = response.json()['PUBLIC_IPV4'] == master_ip
        print(is_healthy)
        return is_healthy, "Master is not healthy yet"

    spin(get_node_health, success, 600, master_ip)
    print("Master is up again.  Master IP: {}".format(master_ip))


def check_master_health(master_ip):
    def get_node_health(master_ip):
        response = None
        try:
            response = dcos.http.post("http://" + master_ip + ":5050/api/v1",json={"type":"GET_HEALTH"})
        except DCOSException as e:
            print("Master IP {} not accessible: ".format(master_ip))
        return response

    def success(response):
        error_message = "Failed to parse json"
        try:
            body = response.json()
        except Exception as e:
            print(e)
            return False, error_message

        is_healthy = response.json()['get_health']['healthy']
        print(is_healthy)
        return is_healthy, "Master is not healthy yet"

    spin(get_node_health, success, 600, master_ip)
    print("Master is up again.  Master IP: {}".format(master_ip))


def setup_module():
    unset_ssl_verification()

#    uninstall()
#    install()
    check_health()


def teardown_module():
    uninstall()


@pytest.mark.recovery
def test_kill_task_in_node():
    kill_task_with_pattern('CassandraDaemon', get_node_host())

    check_health()


@pytest.mark.recovery
def test_kill_all_task_in_node():
    for host in shakedown.get_service_ips(PACKAGE_NAME):
        kill_task_with_pattern('CassandraDaemon', host)

    check_health()


@pytest.mark.recovery
def test_scheduler_died():
    kill_task_with_pattern('cassandra.scheduler.Main', get_scheduler_host())

    check_health()


@pytest.mark.recovery
def test_executor_killed():
    kill_task_with_pattern('cassandra.executor.Main', get_node_host())

    check_health()


@pytest.mark.recovery
def test_all_executors_killed():
    for host in shakedown.get_service_ips(PACKAGE_NAME):
        kill_task_with_pattern('cassandra.executor.Main', host)

    check_health()


@pytest.mark.recovery
def test_master_killed():
    master_leader_ip = shakedown.master_leader_ip()
    kill_task_with_pattern('mesos-master', master_leader_ip)

    _block_on_adminrouter_new(master_leader_ip)


@pytest.mark.recovery
def test_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    kill_task_with_pattern('zookeeper', master_leader_ip)

    _block_on_adminrouter_new(master_leader_ip)


@pytest.mark.recovery
def test_partition():
    host = get_node_host()

    _block_on_adminrouter()
    shakedown.partition_agent(host)
    shakedown.reconnect_agent(host)

    check_health()


@pytest.mark.recovery
def test_partition_master_both_ways():
    master_leader_ip = shakedown.master_leader_ip()
    shakedown.partition_master(master_leader_ip)
    shakedown.reconnect_master(master_leader_ip)

    check_health()


@pytest.mark.recovery
def test_partition_master_incoming():
    master_leader_ip = shakedown.master_leader_ip()
    shakedown.partition_master(master_leader_ip, incoming=True, outgoing=False)
    shakedown.reconnect_master(master_leader_ip)

    check_health()


@pytest.mark.recovery
def test_partition_master_outgoing():
    master_leader_ip = shakedown.master_leader_ip()
    shakedown.partition_master(master_leader_ip, incoming=False, outgoing=True)
    shakedown.reconnect_master(master_leader_ip)

    check_health()


@pytest.mark.recovery
def test_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    for host in hosts:
        shakedown.partition_agent(host)
    for host in hosts:
        shakedown.reconnect_agent(host)

    check_health()


@pytest.mark.recovery
def test_config_update_then_kill_task_in_node():
    host = get_node_host()
    run_planned_operation(
        bump_cpu_count_config,
        lambda: kill_task_with_pattern('CassandraDaemon', host)
    )

    check_health()


@pytest.mark.recovery
def test_config_update_then_kill_all_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    run_planned_operation(
        bump_cpu_count_config,
        lambda: [kill_task_with_pattern('CassandraDaemon', h) for h in hosts]
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
        bump_cpu_count_config,
        lambda: kill_task_with_pattern('cassandra.executor.Main', host)
    )

    check_health()


@pytest.mark.recovery
def test_config_update_then_all_executors_killed():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    run_planned_operation(
        bump_cpu_count_config,
        lambda: [
            kill_task_with_pattern('cassandra.executor.Main', h) for h in hosts
        ]
    )

    check_health()


@pytest.mark.recovery
def test_config_update_then_master_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        bump_cpu_count_config, lambda: kill_task_with_pattern('mesos-master', master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_config_update_then_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        bump_cpu_count_config, lambda: kill_task_with_pattern('zookeeper', master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_config_update_then_partition():
    host = get_node_host()

    def partition():
        shakedown.partition_agent(host)
        shakedown.reconnect_agent(host)

    run_planned_operation(bump_cpu_count_config, partition)

    check_health()


@pytest.mark.recovery
def test_config_update_then_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    def partition():
        for host in hosts:
            shakedown.partition_agent(host)
        for host in hosts:
            shakedown.reconnect_agent(host)

    run_planned_operation(bump_cpu_count_config, partition)

    check_health()


@pytest.mark.recovery
def test_cleanup_then_kill_task_in_node():
    host = get_node_host()
    run_planned_operation(
        run_cleanup,
        lambda: kill_task_with_pattern('CassandraDaemon', host)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_kill_all_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    run_planned_operation(
        run_cleanup,
        lambda: [kill_task_with_pattern('CassandraDaemon', h) for h in hosts]
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_scheduler_died():
    host = get_scheduler_host()
    run_planned_operation(
        run_cleanup,
        lambda: kill_task_with_pattern('cassandra.scheduler.Main', host)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_executor_killed():
    host = get_node_host()
    run_planned_operation(
        run_cleanup,
        lambda: kill_task_with_pattern('cassandra.executor.Main', host)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_all_executors_killed():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    run_planned_operation(
        run_cleanup,
        lambda: [
            kill_task_with_pattern('cassandra.executor.Main', h) for h in hosts
        ]
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_master_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        run_cleanup, lambda: kill_task_with_pattern('mesos-master', master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        run_cleanup, lambda: kill_task_with_pattern('zookeeper', master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_cleanup_then_partition():
    host = get_node_host()

    def partition():
        shakedown.partition_agent(host)
        shakedown.reconnect_agent(host)

    run_planned_operation(run_cleanup, partition)

    check_health()


@pytest.mark.recovery
def test_cleanup_then_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    def partition():
        for host in hosts:
            shakedown.partition_agent(host)
        for host in hosts:
            shakedown.reconnect_agent(host)

    run_planned_operation(run_cleanup, partition)

    check_health()


@pytest.mark.recovery
def test_repair_then_kill_task_in_node():
    host = get_node_host()
    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('CassandraDaemon', host)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_kill_all_task_in_node():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    run_planned_operation(
        run_repair,
        lambda: [kill_task_with_pattern('CassandraDaemon', h) for h in hosts]
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_scheduler_died():
    host = get_scheduler_host()
    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('cassandra.scheduler.Main', host)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_executor_killed():
    host = get_node_host()
    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('cassandra.executor.Main', host)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_all_executors_killed():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)
    run_planned_operation(
        run_repair,
        lambda: [
            kill_task_with_pattern('cassandra.executor.Main', h) for h in hosts
        ]
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_master_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('mesos-master', master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_zk_killed():
    master_leader_ip = shakedown.master_leader_ip()
    run_planned_operation(
        run_repair,
        lambda: kill_task_with_pattern('zookeeper', master_leader_ip)
    )

    check_health()


@pytest.mark.recovery
def test_repair_then_partition():
    host = get_node_host()

    def partition():
        shakedown.partition_agent(host)
        shakedown.reconnect_agent(host)

    run_planned_operation(run_repair, partition)

    check_health()


@pytest.mark.recovery
def test_repair_then_all_partition():
    hosts = shakedown.get_service_ips(PACKAGE_NAME)

    def partition():
        for host in hosts:
            shakedown.partition_agent(host)
        for host in hosts:
            shakedown.reconnect_agent(host)

    run_planned_operation(run_repair, partition)

    check_health()
