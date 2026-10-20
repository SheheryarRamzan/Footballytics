// Event Hubs (live intelligence stream), Cosmos DB serverless (archive + fan profiles) and Blob Storage
// (Event Hubs checkpoints). All keyless: local auth disabled, data-plane RBAC for the app identity.
param location string
param token string
param tags object = {}
param appPrincipalId string
param developerPrincipalId string = ''

// ----------------------------------------------------------------------------- Event Hubs
resource ehns 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evhns-fbx-${token}'
  location: location
  tags: tags
  sku: { name: 'Basic', tier: 'Basic', capacity: 1 }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
  }
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: ehns
  name: 'match-intelligence'
  properties: {
    partitionCount: 4
    messageRetentionInDays: 1
  }
}

var ehSender = '2b629674-e913-4c01-ae53-ef4638d8f975'
var ehReceiver = 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'

resource ehRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in [ehSender, ehReceiver]: {
  name: guid(ehns.id, appPrincipalId, role)
  scope: ehns
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
  }
}]

// ----------------------------------------------------------------------------- Storage (checkpoints)
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stfbx${take(token, 18)}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource checkpoints 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'checkpoints'
}

var blobContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, appPrincipalId, blobContributor)
  scope: storage
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributor)
  }
}

// ----------------------------------------------------------------------------- Cosmos DB (serverless)
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-fbx-${token}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    capabilities: [{ name: 'EnableServerless' }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'footballytics'
  properties: { resource: { id: 'footballytics' } }
}

var containerDefs = [
  { name: 'fans', pk: '/fan_id', ttl: -1 }
  { name: 'events', pk: '/match_id', ttl: 1209600 } // raw events kept 14 days
  { name: 'moments', pk: '/match_id', ttl: -1 }
  { name: 'broadcasts', pk: '/match_id', ttl: -1 }
  { name: 'recaps', pk: '/match_id', ttl: -1 }
  { name: 'matchdays', pk: '/match_id', ttl: -1 }
]

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for c in containerDefs: {
  parent: db
  name: c.name
  properties: {
    resource: {
      id: c.name
      partitionKey: { paths: [c.pk], kind: 'Hash' }
      defaultTtl: c.ttl
    }
  }
}]

var cosmosDataContributor = '00000000-0000-0000-0000-000000000002'
var cosmosPrincipals = filter([appPrincipalId, developerPrincipalId], p => !empty(p))

resource cosmosRoles 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [for p in cosmosPrincipals: {
  parent: cosmos
  name: guid(cosmos.id, p, cosmosDataContributor)
  properties: {
    principalId: p
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    scope: cosmos.id
  }
}]

output eventHubNamespace string = '${ehns.name}.servicebus.windows.net'
output eventHubName string = hub.name
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosDatabase string = db.name
output blobUrl string = storage.properties.primaryEndpoints.blob
output checkpointContainer string = checkpoints.name
