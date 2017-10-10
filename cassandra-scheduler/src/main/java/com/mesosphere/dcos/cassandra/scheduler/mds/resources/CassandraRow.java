package com.adobe.mds.cassandra.cassandraconnection.response;

import java.io.Serializable;

public class CassandraRow implements Serializable{

	/**
	 * 
	 */
	private static final long serialVersionUID = 1L;
	
	private String key;
	private String C0;
	private String C1;
	private String C2;
	private String C3;
	private String C4;
	
	public String getKey() {
		return key;
	}
	public void setKey(String key) {
		this.key = key;
	}
	public String getC0() {
		return C0;
	}
	public void setC0(String c0) {
		C0 = c0;
	}
	public String getC1() {
		return C1;
	}
	public void setC1(String c1) {
		C1 = c1;
	}
	public String getC2() {
		return C2;
	}
	public void setC2(String c2) {
		C2 = c2;
	}
	public String getC3() {
		return C3;
	}
	public void setC3(String c3) {
		C3 = c3;
	}
	public String getC4() {
		return C4;
	}
	public void setC4(String c4) {
		C4 = c4;
	}
	
	
}
