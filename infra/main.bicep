// Footballytics infrastructure (azd-compatible, subscription scope).
targetScope = 'subscription'

@minLength(1)
@maxLength(32)
@description('Environment name, e.g. dev. Used to derive resource names.')
param environmentName string

@description('Primary region (East US 2 has quota for every model we use)')
param location string = 'eastus2'

@description('Object ID of the developer running the deployment (azd sets AZURE_PRINCIPAL_ID)')
param principalId string = ''

var tags = { 'azd-env-name': environmentName, project: 'footballytics' }
var token = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-footballytics-${environmentName}'
  location: location
  tags: tags
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    location: location
    accountName: 'fbx-ai-${token}'
    tags: tags
    developerPrincipalId: principalId
    deployments: [
      // Reasoning agents (Analyst, Director, Recap): quality with controllable reasoning effort.
      { name: 'gpt-5-mini', model: 'gpt-5-mini', version: '2025-08-07', sku: 'GlobalStandard', capacity: 200 }
      // Low-latency live captions, Host narration and translation.
      { name: 'gpt-4.1-mini', model: 'gpt-4.1-mini', version: '2025-04-14', sku: 'GlobalStandard', capacity: 150 }
      // Voice: talk-to-your-pundit and expressive multilingual TTS.
      { name: 'gpt-realtime-mini', model: 'gpt-realtime-mini', version: '2025-12-15', sku: 'GlobalStandard', capacity: 10 }
      { name: 'gpt-4o-mini-tts', model: 'gpt-4o-mini-tts', version: '2025-12-15', sku: 'GlobalStandard', capacity: 20 }
    ]
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.accountName
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_OPENAI_ENDPOINT string = foundry.outputs.openAiEndpoint
output AZURE_AI_ENDPOINT string = foundry.outputs.accountEndpoint
