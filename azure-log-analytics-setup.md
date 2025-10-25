# Azure Log Analytics Setup for CallCenter AI

## 1. Create Log Analytics Workspace

```bash
# Create Log Analytics workspace
az monitor log-analytics workspace create \
  --resource-group CallCenterAi-Test \
  --workspace-name callcenterai-logs \
  --location centralus
```

## 2. Get Workspace ID and Key

```bash
# Get workspace ID
WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group CallCenterAi-Test \
  --workspace-name callcenterai-logs \
  --query customerId -o tsv)

# Get workspace key
WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group CallCenterAi-Test \
  --workspace-name callcenterai-logs \
  --query primarySharedKey -o tsv)

echo "Workspace ID: $WORKSPACE_ID"
echo "Workspace Key: $WORKSPACE_KEY"
```

## 3. Update Container Command with Log Analytics

Add these environment variables to your container command:

```bash
# Add these to your --environment-variables section:
LOG_ANALYTICS_WORKSPACE_ID="$WORKSPACE_ID" \
LOG_ANALYTICS_WORKSPACE_KEY="$WORKSPACE_KEY" \
LOG_ANALYTICS_ENABLED=true \
```

## 4. View Logs in Azure Portal

1. Go to Azure Portal → Log Analytics workspaces
2. Select your workspace: `callcenterai-logs`
3. Go to "Logs" section
4. Run queries like:

```kusto
// View all logs
CallCenterAI_Logs_CL

// Filter by log level
CallCenterAI_Logs_CL
| where Level_s == "ERROR"

// Filter by category
CallCenterAI_Logs_CL
| where Category_s == "SECURITY"

// View API requests
CallCenterAI_Logs_CL
| where Category_s == "API"
| project TimeGenerated, Message, RequestId_g, Method_s, Endpoint_s
```

## 5. Alternative: Use Azure Container Insights

For automatic log collection, you can also use Azure Container Insights:

```bash
# Enable Container Insights
az monitor log-analytics workspace enable-azure-monitor \
  --resource-group CallCenterAi-Test \
  --workspace-name callcenterai-logs
```

## 6. Benefits of Azure Log Analytics

- **Centralized Logging**: All logs in one place
- **Advanced Queries**: KQL (Kusto Query Language) for complex analysis
- **Alerting**: Set up alerts for errors, performance issues
- **Retention**: Configurable log retention (30 days to 2 years)
- **Security**: Built-in security and compliance features
- **Cost Effective**: Pay only for data ingested
