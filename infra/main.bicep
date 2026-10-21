// Footballytics infrastructure (azd-compatible, subscription scope).
//
//   Foundry (models, keyless)  <- api / archiver identity
//   Container Apps: api (web, REST, WebSocket, MCP, agents)  -> Event Hubs -> archiver -> Cosmos DB
//   Monitoring: Log Analytics + Application Insights (OpenTelemetry from app and Agent Framework)
targetScope = 'subscription'

@minLength(1)
@maxLength(32)
@description('Environment name, e.g. dev. Used to derive resource names.')
param environmentName string

@description('Primary region (East US 2 has quota for every model we use)')
param location string = 'eastus2'

@description('Object ID of the developer running the deployment (azd sets AZURE_PRINCIPAL_ID)')
param principalId string = ''

@description('Deploy the container apps (set false for the first pass, before an image exists)')
param deployApps bool = true

@description('Container image for api and archiver, e.g. <registry>.azurecr.io/footballytics:<tag>')
param image string = ''

@description('Simulation speed (sim seconds per wall second) for the public demo')
param speed string = '4'

var tags = { 'azd-env-name': environmentName, project: 'footballytics' }
var token = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-footballytics-${environmentName}'
  location: location
  tags: tags
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  scope: rg
  params: { location: location, token: token, tags: tags }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: { location: location, token: token, tags: tags }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    location: location
    accountName: 'fbx-ai-${token}'
    tags: tags
    developerPrincipalId: principalId
    appPrincipalId: registry.outputs.identityPrincipalId
    appInsightsId: monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    deployments: [
      // Reasoning agents (Analyst, Director, Recap): quality with controllable reasoning effort.
      { name: 'gpt-5-mini', model: 'gpt-5-mini', version: '2025-08-07', sku: 'GlobalStandard', capacity: 200 }
      // Low-latency live captions, Host narration, translation and the Pundit.
      { name: 'gpt-4.1-mini', model: 'gpt-4.1-mini', version: '2025-04-14', sku: 'GlobalStandard', capacity: 150 }
      // Voice: talk-to-your-pundit and expressive multilingual TTS.
      { name: 'gpt-realtime-mini', model: 'gpt-realtime-mini', version: '2025-12-15', sku: 'GlobalStandard', capacity: 10 }
      { name: 'gpt-4o-mini-tts', model: 'gpt-4o-mini-tts', version: '2025-12-15', sku: 'GlobalStandard', capacity: 20 }
    ]
  }
}

module data 'modules/data.bicep' = {
  name: 'data'
  scope: rg
  params: {
    location: location
    token: token
    tags: tags
    appPrincipalId: registry.outputs.identityPrincipalId
    developerPrincipalId: principalId
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  scope: rg
  name: 'log-fbx-${token}'
}

module apps 'modules/apps.bicep' = if (deployApps) {
  name: 'apps'
  scope: rg
  params: {
    location: location
    token: token
    tags: tags
    logAnalyticsCustomerId: monitoring.outputs.logAnalyticsCustomerId
    logAnalyticsSharedKey: logs.listKeys().primarySharedKey
    identityId: registry.outputs.identityId
    identityClientId: registry.outputs.identityClientId
    registryServer: registry.outputs.registryServer
    image: empty(image) ? 'mcr.microsoft.com/k8se/quickstart:latest' : image
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    env: [
      { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundry.outputs.projectEndpoint }
      { name: 'AZURE_OPENAI_ENDPOINT', value: foundry.outputs.openAiEndpoint }
      { name: 'MODEL_TTS', value: 'gpt-4o-mini-tts' }
      { name: 'MODEL_REASONING', value: 'gpt-5-mini' }
      { name: 'MODEL_FAST', value: 'gpt-4.1-mini' }
      { name: 'ANALYST_MODEL', value: 'reasoning' }
      { name: 'ANALYST_EFFORT', value: 'minimal' }
      { name: 'NEWSROOM_MIN_IMPORTANCE', value: '50' }
      { name: 'EVENTHUB_NAMESPACE', value: data.outputs.eventHubNamespace }
      { name: 'EVENTHUB_NAME', value: data.outputs.eventHubName }
      { name: 'COSMOS_ENDPOINT', value: data.outputs.cosmosEndpoint }
      { name: 'COSMOS_DATABASE', value: data.outputs.cosmosDatabase }
      { name: 'CHECKPOINT_BLOB_URL', value: data.outputs.blobUrl }
      { name: 'CHECKPOINT_CONTAINER', value: data.outputs.checkpointContainer }
      { name: 'AUTOLOOP', value: '1' }
      { name: 'TRACE_CONTENT', value: '1' } // synthetic data: include prompts/outputs in Foundry traces
      { name: 'PUBLIC_DEMO', value: '1' } // one shared live matchday: Studio restart/speed are read-only in public
      { name: 'SPEED', value: speed }
      { name: 'MATCHDAY', value: '9' }
    ]
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.registryName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.registryServer
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.accountName
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_OPENAI_ENDPOINT string = foundry.outputs.openAiEndpoint
output AZURE_AI_ENDPOINT string = foundry.outputs.accountEndpoint
output EVENTHUB_NAMESPACE string = data.outputs.eventHubNamespace
output EVENTHUB_NAME string = data.outputs.eventHubName
output COSMOS_ENDPOINT string = data.outputs.cosmosEndpoint
output APP_IDENTITY_CLIENT_ID string = registry.outputs.identityClientId
output API_URL string = apps.?outputs.apiUrl ?? ''
