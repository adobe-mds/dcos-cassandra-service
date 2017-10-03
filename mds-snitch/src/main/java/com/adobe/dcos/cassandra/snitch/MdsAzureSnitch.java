package com.adobe.dcos.cassandra.snitch;


/**
 * Created by nitjain on 9/26/17.
 */

import java.io.DataInputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import org.apache.cassandra.db.SystemKeyspace;
import org.apache.cassandra.exceptions.ConfigurationException;
import org.apache.cassandra.gms.ApplicationState;
import org.apache.cassandra.gms.EndpointState;
import org.apache.cassandra.gms.Gossiper;
import org.apache.cassandra.io.util.FileUtils;
import org.apache.cassandra.locator.AbstractNetworkTopologySnitch;
import org.apache.cassandra.locator.SnitchProperties;
import org.apache.cassandra.utils.FBUtilities;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class MdsAzureSnitch extends AbstractNetworkTopologySnitch {


    private static final Logger LOGGER = LoggerFactory.getLogger(com.adobe.dcos.cassandra.snitch.MdsAzureSnitch.class);

    protected static final String REGION_NAME_QUERY_URL =
                    "http://169.254.169.254/metadata/instance/compute/location?api-version=2017-04-02&format=text";
    protected static final String FAULTDOMAIN_NAME_QUERY_URL =
                    "http://169.254.169.254/metadata/instance/compute/platformFaultDomain?api-version=2017-04-02&format=text";

    private static final String DEFAULT_DC = "UNKNOWN-DC";
    private static final String DEFAULT_RACK = "UNKNOWN-RACK";
    private Map<InetAddress, Map<String, String>> savedEndpoints;
    protected String faultDomain;
    protected String azureRegion;
    private final String CLOUD_PROVIDER_PREFIX = "AZURE-";
    
    public MdsAzureSnitch() throws IOException, ConfigurationException {
        String apiResult;
        apiResult = azureApiCall(REGION_NAME_QUERY_URL);
        LOGGER.info("Azure Metadata API Region {}", apiResult);
		azureRegion = CLOUD_PROVIDER_PREFIX + apiResult;
        apiResult = azureApiCall(FAULTDOMAIN_NAME_QUERY_URL);
        LOGGER.info("Azure Metadata API FaultDomain {}", apiResult);
        faultDomain = apiResult;
        final String datacenterSuffix = (new SnitchProperties()).get("dc_suffix", "");
        azureRegion = azureRegion.concat(datacenterSuffix);
        LOGGER.info("MdsAzureSnitch using region: {}, zone: {}.", azureRegion, faultDomain);
    }

    String azureApiCall(final String url) throws IOException, ConfigurationException {
        // Populate the region and zone by introspection, fail if 404 on
        // metadata
        final HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        DataInputStream d = null;
        try {
            conn.setRequestMethod("GET");
            conn.setRequestProperty("Metadata", "true");
            if (conn.getResponseCode() != 200)
                throw new ConfigurationException("MdsAzureSnitch was unable to execute the API call. Not an azure VM?");

            final int cl = conn.getContentLength();
            final byte[] b = new byte[cl];
            d = new DataInputStream((FilterInputStream) conn.getContent());
            d.readFully(b);
            return new String(b, StandardCharsets.UTF_8);
        } finally {
            FileUtils.close(d);
            conn.disconnect();
        }
    }

    public String getRack(final InetAddress endpoint) {
        if (endpoint.equals(FBUtilities.getBroadcastAddress()))
            return faultDomain;
        final EndpointState state = Gossiper.instance.getEndpointStateForEndpoint(endpoint);
        if (state == null || state.getApplicationState(ApplicationState.RACK) == null) {
            if (savedEndpoints == null)
                savedEndpoints = SystemKeyspace.loadDcRackInfo();
            if (savedEndpoints.containsKey(endpoint))
                return savedEndpoints.get(endpoint).get("rack");
            return DEFAULT_RACK;
        }
        return state.getApplicationState(ApplicationState.RACK).value;
    }

    public String getDatacenter(final InetAddress endpoint) {
        if (endpoint.equals(FBUtilities.getBroadcastAddress()))
            return azureRegion;
        final EndpointState state = Gossiper.instance.getEndpointStateForEndpoint(endpoint);
        if (state == null || state.getApplicationState(ApplicationState.DC) == null) {
            if (savedEndpoints == null)
                savedEndpoints = SystemKeyspace.loadDcRackInfo();
            if (savedEndpoints.containsKey(endpoint))
                return savedEndpoints.get(endpoint).get("data_center");
            return DEFAULT_DC;
        }
        return state.getApplicationState(ApplicationState.DC).value;
    }
}


