package com.mesosphere.dcos.cassandra.scheduler.mds.resources;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.inject.Inject;
import javax.ws.rs.BadRequestException;
import javax.ws.rs.Consumes;
import javax.ws.rs.GET;
import javax.ws.rs.InternalServerErrorException;
import javax.ws.rs.NotFoundException;
import javax.ws.rs.POST;
import javax.ws.rs.PUT;
import javax.ws.rs.Path;
import javax.ws.rs.PathParam;
import javax.ws.rs.Produces;
import javax.ws.rs.ServiceUnavailableException;
import javax.ws.rs.core.MediaType;
import javax.ws.rs.core.Response;

import org.apache.mesos.config.ConfigStoreException;
import org.apache.mesos.dcos.Capabilities;
import org.apache.mesos.offer.VolumeRequirement.VolumeType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.datastax.driver.core.BoundStatement;
import com.datastax.driver.core.PreparedStatement;
import com.datastax.driver.core.ResultSet;
import com.datastax.driver.core.Row;
import com.datastax.driver.core.Session;
import com.datastax.driver.core.exceptions.NoHostAvailableException;
import com.datastax.driver.core.exceptions.QueryExecutionException;
import com.datastax.driver.core.exceptions.QueryValidationException;
import com.datastax.driver.core.utils.Bytes;
import com.mesosphere.dcos.cassandra.common.config.ConfigurationManager;
import com.mesosphere.dcos.cassandra.common.tasks.CassandraState;

@Path("/v1/itest")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
public class MdsItestManageResource {
	private static final Logger LOGGER = LoggerFactory.getLogger(MdsItestManageResource.class);
	private final ConfigurationManager configurationManager;
	private final Capabilities capabilities;
	private final CassandraState state;
	private final Integer maxRowLimit = 500000;

	@Inject
	public MdsItestManageResource(Capabilities capabilities, CassandraState state,
	        ConfigurationManager configurationManager) {
		this.configurationManager = configurationManager;
		this.capabilities = capabilities;
		this.state = state;
	}

	@PUT
	@Path("/keyspace/{keyspace}")
	public Response alterKeyspace(@PathParam("keyspace") final String keyspace,
	        AlterSystemAuthRequest alterSysteAuthRequest) throws ConfigStoreException {

		try (Session session = MdsCassandraUtills.getSession(alterSysteAuthRequest.getCassandraAuth(), capabilities,
		        state, configurationManager)) {
			// session = getSession(alterSysteAuthRequest.getCassandraAuth());
			String dcRf = MdsCassandraUtills
			        .getDataCenterVsReplicationFactorString(alterSysteAuthRequest.getDataCenterVsReplicationFactor());
			String query = "ALTER KEYSPACE " + keyspace + " WITH REPLICATION = {'class' : 'NetworkTopologyStrategy', "
			        + dcRf + "};";
			LOGGER.info("Alter keyspace1 query:" + query);

			session.execute(query);
		} catch (NoHostAvailableException e) {
			return Response.status(Response.Status.SERVICE_UNAVAILABLE).entity(e.getMessage()).build();
		} catch (QueryExecutionException e) {
			return Response.status(Response.Status.INTERNAL_SERVER_ERROR).entity(e.getMessage()).build();
		} catch (QueryValidationException e) {
			return Response.status(Response.Status.BAD_REQUEST).entity(e.getMessage()).build();
		} catch (Exception e) {
			return Response.status(Response.Status.INTERNAL_SERVER_ERROR).entity(e.getMessage()).build();
		}

		return Response.status(Response.Status.OK).entity("Successfull").build();
	}

	@GET
	@Path("/sstables/files")
	public SSTablesResponse getSSTablesFiles() throws IOException, InterruptedException {
		SSTablesResponse ssTablesResponse = new SSTablesResponse();
		VolumeType diskType = configurationManager.getTargetConfig().getCassandraConfig().getDiskType();
		String dataPath = "";
		if (VolumeType.MOUNT.equals(diskType)) {
			dataPath = "/dcos/volume1";
		} else {
			dataPath = "/var/lib/mesos/slave/volumes/roles/"
			        + configurationManager.getTargetConfig().getServiceConfig().getRole();
		}

		String command = "find " + dataPath + " -name *.db* |  rev | cut -d/ -f1 | rev";
		List<String> commands = new ArrayList<String>();
		commands.add("/bin/sh");
		commands.add("-c");
		commands.add(command);
		Runtime run = Runtime.getRuntime();
		Process pr = run.exec(commands.toArray(new String[commands.size()]));
		pr.waitFor();
		BufferedReader buf = new BufferedReader(new InputStreamReader(pr.getInputStream()));
		String line = "";
		while ((line = buf.readLine()) != null) {
			ssTablesResponse.addSSTablesFileName(line);
		}
		return ssTablesResponse;
	}

	@POST
	@Path("/createdcoskeyspace")
	public Response createDcosKeyspace(CassandraAuth cassandraAuth) {
		try (Session session = MdsCassandraUtills.getSession(cassandraAuth, capabilities, state,
		        configurationManager)) {
			session.execute(
			        "CREATE KEYSPACE IF NOT EXISTS dcos WITH REPLICATION = { 'class' : 'SimpleStrategy', 'replication_factor' : 3 };");
			session.execute("USE dcos");
			session.execute("CREATE TABLE IF NOT EXISTS pairs (key varchar, value varchar, PRIMARY KEY(key));");
		} catch (NoHostAvailableException e) {
			return Response.status(Response.Status.SERVICE_UNAVAILABLE).entity(e.getMessage()).build();
		} catch (QueryExecutionException e) {
			return Response.status(Response.Status.INTERNAL_SERVER_ERROR).entity(e.getMessage()).build();
		} catch (QueryValidationException e) {
			return Response.status(Response.Status.BAD_REQUEST).entity(e.getMessage()).build();
		} catch (Exception e) {
			return Response.status(Response.Status.INTERNAL_SERVER_ERROR).entity(e.getMessage()).build();
		}
		return Response.status(Response.Status.OK).entity("Successfull").build();
	}

	@PUT
	@Path("/setkey/{key}/{value}")
	public Response setKey(@PathParam("key") final String key, @PathParam("value") final String value,
	        CassandraAuth cassandraAuth) {
		try (Session session = MdsCassandraUtills.getSession(cassandraAuth, capabilities, state,
		        configurationManager)) {
			PreparedStatement ps = session.prepare("insert into pairs (key, value) values (?, ?)");
			BoundStatement boundStatement = ps.bind(key, value);
			session.execute(boundStatement);
		} catch (NoHostAvailableException e) {
			return Response.status(Response.Status.SERVICE_UNAVAILABLE).entity(e.getMessage()).build();
		} catch (QueryExecutionException e) {
			return Response.status(Response.Status.INTERNAL_SERVER_ERROR).entity(e.getMessage()).build();
		} catch (QueryValidationException e) {
			return Response.status(Response.Status.BAD_REQUEST).entity(e.getMessage()).build();
		} catch (Exception e) {
			return Response.status(Response.Status.INTERNAL_SERVER_ERROR).entity(e.getMessage()).build();
		}
		return Response.status(Response.Status.OK).entity("Successfull").build();
	}

	@GET
	@Path("/getkey/{key}")
	public String getKey(@PathParam("key") final String key, CassandraAuth cassandraAuth) {
		try (Session session = MdsCassandraUtills.getSession(cassandraAuth, capabilities, state,
		        configurationManager)) {
			PreparedStatement ps = session.prepare("select value from dcos.pairs where key=?");
			BoundStatement boundStatement = ps.bind(key);
			ResultSet rs = session.execute(boundStatement);

			Row row = rs.one();
			if (row == null) {
				throw new NotFoundException();
			}
			return row.get(0, String.class);
		} catch (NoHostAvailableException e) {
			throw new ServiceUnavailableException(e.getMessage());
		} catch (QueryExecutionException e) {
			throw new InternalServerErrorException(e.getMessage());
		} catch (QueryValidationException e) {
			throw new BadRequestException(e.getMessage());
		} catch (Exception e) {
			throw new InternalServerErrorException(e.getMessage());
		}
	}

	@GET
	@Path("/stress/{keyspace}/{table}/{rowlimit}")
	public CassandraCollectionData getStressData(@PathParam("keyspace") final String keyspace,
	        @PathParam("table") final String table, @PathParam("rowlimit") Integer rowlimit,
	        CassandraAuth cassandraAuth) {
		LOGGER.info("stress data colleciton limit:" + rowlimit);

		CassandraCollectionData data = new CassandraCollectionData();
		Map<String, CassandraRow> keyVsValue = new HashMap<String, CassandraRow>();
		data.setCassadraData(keyVsValue);
		rowlimit = (rowlimit > maxRowLimit) ? maxRowLimit : rowlimit;
		LOGGER.info("final limit:" + rowlimit);
		try (Session session = MdsCassandraUtills.getSession(cassandraAuth, capabilities, state,
		        configurationManager)) {
			PreparedStatement ps = session.prepare("select * from " + keyspace + "." + table + " limit " + rowlimit);
			BoundStatement boundStatement = ps.bind();
			LOGGER.info("stress query string = " + ps.getQueryString());
			ResultSet rs = session.execute(boundStatement);
			while (!rs.isExhausted()) {
				Row one = rs.one();
				CassandraRow ks = new CassandraRow();
				String key = Bytes.toHexString(one.getBytes("key"));
				String C0 = Bytes.toHexString(one.getBytes("C0"));
				String C1 = Bytes.toHexString(one.getBytes("C1"));
				String C2 = Bytes.toHexString(one.getBytes("C2"));
				String C3 = Bytes.toHexString(one.getBytes("C3"));
				String C4 = Bytes.toHexString(one.getBytes("C4"));
				ks.setKey(key);
				ks.setC0(C0);
				ks.setC1(C1);
				ks.setC2(C2);
				ks.setC3(C3);
				ks.setC4(C4);
				keyVsValue.put(key, ks);
			}
		} catch (NoHostAvailableException e) {
			throw new ServiceUnavailableException(e.getMessage());
		} catch (QueryExecutionException e) {
			throw new InternalServerErrorException(e.getMessage());
		} catch (QueryValidationException e) {
			throw new BadRequestException(e.getMessage());
		} catch (Exception e) {
			throw new InternalServerErrorException(e.getMessage());
		}
		LOGGER.info("stress data collected size:" + data.getCassadraData().size());
		return data;
	}

	@POST
	@Path("/stressquery")
	public CassandraCollectionData getStressQueryForKeys(StressQueryKeys stressQueryKeys) {
		LOGGER.info("stress query keyspace = " + stressQueryKeys.getKeyspaceName() + " table name = "
		        + stressQueryKeys.getTableName() + " key size=" + stressQueryKeys.getKeys().size());
		Map<String, CassandraRow> keyVsValue = new HashMap<String, CassandraRow>();
		CassandraCollectionData data = new CassandraCollectionData();
		data.setCassadraData(keyVsValue);

		try (Session session = MdsCassandraUtills.getSession(stressQueryKeys.getCassandraAuth(), capabilities, state,
		        configurationManager)) {
			String inKeys = prepareInQueryFromKeys(stressQueryKeys);
			PreparedStatement ps = session
			        .prepare("select * from " + stressQueryKeys.getKeyspaceName() + "." + stressQueryKeys.getTableName()
			                + " where " + stressQueryKeys.getColoumName() + " in (" + inKeys + ")");
			BoundStatement boundStatement = ps.bind();
			LOGGER.info("stress query string = " + ps.getQueryString());
			ResultSet rs = session.execute(boundStatement);
			while (!rs.isExhausted()) {
				Row one = rs.one();
				CassandraRow ks = new CassandraRow();
				// String key = new String
				// (one.getBytes("key").array(),"UTF-8");
				String key = Bytes.toHexString(one.getBytes("key"));
				String C0 = Bytes.toHexString(one.getBytes("C0"));
				String C1 = Bytes.toHexString(one.getBytes("C1"));
				String C2 = Bytes.toHexString(one.getBytes("C2"));
				String C3 = Bytes.toHexString(one.getBytes("C3"));
				String C4 = Bytes.toHexString(one.getBytes("C4"));
				ks.setKey(key);
				ks.setC0(C0);
				ks.setC1(C1);
				ks.setC2(C2);
				ks.setC3(C3);
				ks.setC4(C4);
				keyVsValue.put(key, ks);
			}
		} catch (NoHostAvailableException e) {
			throw new ServiceUnavailableException(e.getMessage());
		} catch (QueryExecutionException e) {
			throw new InternalServerErrorException(e.getMessage());
		} catch (QueryValidationException e) {
			throw new BadRequestException(e.getMessage());
		} catch (Exception e) {
			throw new InternalServerErrorException(e.getMessage());
		}
		LOGGER.info("stress query data collected size:" + data.getCassadraData().size());
		return data;
	}

	private String prepareInQueryFromKeys(StressQueryKeys stressQueryKeys) {
		List<String> keys = stressQueryKeys.getKeys();
		String inKeys = "";
		inKeys = keys.remove(0);

		for (String key : keys) {
			inKeys = inKeys + "," + key;
		}
		return inKeys;
	}
}
