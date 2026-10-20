// Microsoft Foundry: AI Services account (with project management), a project, model
// deployments, and keyless (Entra ID) role assignments for the developer and the app identity.

@description('Azure region for the Foundry resource')
param location string

@description('Globally unique name for the Foundry (AI Services) account')
param accountName string

@description('Foundry project name')
param projectName string = 'footballytics'

@description('Model deployments: [{ name, model, version, sku, capacity }]')
param deployments array

@description('Object ID of the developer (user) to grant data-plane access to')
param developerPrincipalId string = ''

@description('Principal ID of the application managed identity')
param appPrincipalId string = ''

param tags object = {}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true // keyless only: every caller authenticates with Entra ID
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Footballytics'
    description: 'Agentic personal match broadcasts from synthetic football events'
  }
}

@batchSize(1)
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [for d in deployments: {
  parent: account
  name: d.name
  dependsOn: [project] // the account accepts one write at a time
  sku: { name: d.sku, capacity: d.capacity }
  properties: {
    model: { format: 'OpenAI', name: d.model, version: d.version }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}]

// Built-in roles
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // formerly 'Azure AI User'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var cognitiveServicesOpenAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

var principals = filter([
  { id: developerPrincipalId, type: 'User' }
  { id: appPrincipalId, type: 'ServicePrincipal' }
], p => !empty(p.id))

var roles = [foundryUser, cognitiveServicesUser, cognitiveServicesOpenAiUser]

resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for pair in flatten(map(principals, p => map(roles, r => { principal: p, role: r }))): {
  name: guid(account.id, pair.principal.id, pair.role)
  scope: account
  dependsOn: [modelDeployments]
  properties: {
    principalId: pair.principal.id
    principalType: pair.principal.type
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', pair.role)
  }
}]

output accountName string = account.name
output accountEndpoint string = 'https://${account.name}.services.ai.azure.com'
output openAiEndpoint string = 'https://${account.name}.openai.azure.com'
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output projectName string = project.name
