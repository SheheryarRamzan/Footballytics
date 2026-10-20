// App identity (user-assigned) and the container registry it pulls from.
param location string
param token string
param tags object = {}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-fbx-${token}'
  location: location
  tags: tags
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crfbx${take(token, 20)}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, acrPull)
  scope: acr
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

output identityId string = identity.id
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
output registryName string = acr.name
output registryServer string = acr.properties.loginServer
