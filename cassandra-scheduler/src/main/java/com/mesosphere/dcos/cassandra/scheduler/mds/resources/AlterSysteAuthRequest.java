package com.mesosphere.dcos.cassandra.scheduler.mds.resources;

import java.util.Map;

public class AlterSysteAuthRequest {

    private CassandraAuth cassandraAuth;
    private Map<String, Integer> dataCenterVsReplicationFactor;

    public CassandraAuth getCassandraAuth() {
        return cassandraAuth;
    }

    public void setCassandraAuth(CassandraAuth cassandraAuth) {
        this.cassandraAuth = cassandraAuth;
    }

    public Map<String, Integer> getDataCenterVsReplicationFactor() {
        return dataCenterVsReplicationFactor;
    }

    public void setDataCenterVsReplicationFactor(Map<String, Integer> dataCenterVsReplicationFactor) {
        this.dataCenterVsReplicationFactor = dataCenterVsReplicationFactor;
    }

    @Override
    public String toString() {
        return "AlterSysteAuthRequest [cassandraAuth=" + cassandraAuth + ", dataCenterVsReplicationFactor="
                        + dataCenterVsReplicationFactor + "]";
    }

}
