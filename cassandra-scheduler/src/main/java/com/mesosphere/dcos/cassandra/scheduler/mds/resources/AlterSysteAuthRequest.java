package com.mesosphere.dcos.cassandra.scheduler.mds.resources;

import java.util.Map;

public class AlterSysteAuthRequest {

    private CassandraAuth cassandraAuth;
    private Map<String, Integer> dcVsRF;


    public CassandraAuth getCassandraAuth() {
        return cassandraAuth;
    }

    public void setCassandraAuth(CassandraAuth cassandraAuth) {
        this.cassandraAuth = cassandraAuth;
    }


    public Map<String, Integer> getDcVsRF() {
        return dcVsRF;
    }


    public void setDcVsRF(Map<String, Integer> dcVsRF) {
        this.dcVsRF = dcVsRF;
    }

    @Override
    public String toString() {
        return "AlterSysteAuthRequest [cassandraAuth=" + cassandraAuth + ", dcVsRF=" + dcVsRF + "]";
    }
}
