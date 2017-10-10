package com.adobe.mds.cassandra.cassandraconnection.response;

import java.util.Map;

public class CassandraCollectionData {

	private Map<String, CassandraRow> cassadraData;
	private String message;

	public Map<String, CassandraRow> getCassadraData() {
		return cassadraData;
	}

	public void setCassadraData(Map<String, CassandraRow> cassadraData) {
		this.cassadraData = cassadraData;
	}

	public String getMessage() {
		return message;
	}

	public void setMessage(String message) {
		this.message = message;
	}
}
