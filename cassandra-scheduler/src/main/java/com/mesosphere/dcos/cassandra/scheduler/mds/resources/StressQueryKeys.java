package com.adobe.mds.cassandra.cassandraconnection.request;

import java.util.List;

public class StressQueryKeys {

	private String keyspaceName;
	private String tableName;
	private String coloumName;
	private List<String> keys;
	private CassandraAuth cassandraAuth;

	public List<String> getKeys() {
		return keys;
	}

	public void setKeys(List<String> keys) {
		this.keys = keys;
	}

	public String getKeyspaceName() {
		return keyspaceName;
	}

	public void setKeyspaceName(String keyspaceName) {
		this.keyspaceName = keyspaceName;
	}

	public String getTableName() {
		return tableName;
	}

	public void setTableName(String tableName) {
		this.tableName = tableName;
	}

	public String getColoumName() {
		return coloumName;
	}

	public void setColoumName(String coloumName) {
		this.coloumName = coloumName;
	}

	public CassandraAuth getCassandraAuth() {
		return cassandraAuth;
	}

	public void setCassandraAuth(CassandraAuth cassandraAuth) {
		this.cassandraAuth = cassandraAuth;
	}
	
}
