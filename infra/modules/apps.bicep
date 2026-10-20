// Container Apps environment with two apps from one image:
//   api       public ingress (web app, REST, WebSocket, MCP); runs the live hub + agent newsroom
//   archiver  event-driven worker: Event Hubs -> Cosmos DB (no ingress)
param location string
param token string
param tags object = {}
param logAnalyticsCustomerId string
@secure()
param logAnalyticsSharedKey string
param identityId string
param identityClientId string
param registryServer string
param image string
@secure()
param appInsightsConnectionString string
param env array // shared plain env vars: [{ name, value }]

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-fbx-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logAnalyticsCustomerId, sharedKey: logAnalyticsSharedKey }
    }
  }
}

var common = concat(env, [
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights' }
  // The app's public hostname, allow-listed by the MCP server's DNS-rebinding protection.
  { name: 'MCP_ALLOWED_HOSTS', value: 'ca-fbx-api-${take(token, 8)}.${cae.properties.defaultDomain}' }
])

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-fbx-api-${take(token, 8)}'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{ server: registryServer, identity: identityId }]
      secrets: [{ name: 'appinsights', value: appInsightsConnectionString }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: common
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      // One replica owns the live simulation; viewers scale through WebSocket fan-out and Event Hubs consumers.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

resource archiver 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-fbx-arc-${take(token, 8)}'
  location: location
  tags: union(tags, { 'azd-service-name': 'archiver' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: registryServer, identity: identityId }]
      secrets: [{ name: 'appinsights', value: appInsightsConnectionString }]
    }
    template: {
      containers: [
        {
          name: 'archiver'
          image: image
          command: ['python', '-m', 'footballytics.archiver']
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: common
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output apiName string = api.name
output archiverName string = archiver.name
output environmentName string = cae.name
