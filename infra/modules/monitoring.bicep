// Log Analytics + workspace-based Application Insights (OpenTelemetry target for app and agents).
param location string
param token string
param tags object = {}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-fbx-${token}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-fbx-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

output logAnalyticsId string = logs.id
output logAnalyticsCustomerId string = logs.properties.customerId
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output appInsightsId string = appInsights.id
