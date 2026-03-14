# Azure Setup — OIDC for GitHub Actions

## Why OIDC (not publish profiles)

Publish profiles are shared secrets stored in GitHub Secrets that never rotate. OIDC federated credentials give GitHub Actions a **short-lived token per run** — no stored secrets in GitHub, no rotation burden, no exfiltration risk. This is the pattern used across Azure internal services.

## One-time setup (5 minutes)

### 1. Run the setup script

```powershell
az login
cd azure/setup
.\setup-oidc.ps1
```

This creates:
- Entra app registration (`codegamified-github-actions`)
- Service principal
- Federated credentials for `environment:production` and `ref:refs/heads/main`
- Contributor role assignment on subscription `835a9ee3-aef1-4ebb-a98f-6bc9b7886a7f`

### 2. Add GitHub repo secrets

The script outputs three values. Add them at:
**https://github.com/CodeGamified/codegamified.github.io/settings/secrets/actions**

| Secret | Source |
|---|---|
| `AZURE_CLIENT_ID` | Script output (Entra app client ID) |
| `AZURE_TENANT_ID` | Script output (Entra tenant ID) |
| `AZURE_SUBSCRIPTION_ID` | `835a9ee3-aef1-4ebb-a98f-6bc9b7886a7f` |
| `OAUTH_CLIENT_ID` | From GitHub OAuth App settings |
| `OAUTH_CLIENT_SECRET` | From GitHub OAuth App settings |

### 3. Create GitHub environment

Go to **https://github.com/CodeGamified/codegamified.github.io/settings/environments**

Create environment: `production`

Recommended protection rules:
- **Required reviewers**: add yourself (optional, prevents accidental deploys)
- **Deployment branches**: `main` only

### 4. Provision Azure resources

Go to **Actions** tab → **Provision Azure Infra** → **Run workflow**

Pick your region (default: `westus2`) and function app name (default: `codegamified-auth`).

The workflow creates: resource group, storage account, Function App (Flex Consumption/Linux/.NET 8 isolated), and sets app settings.

### 5. Deploy

Push any change to `azure/token-proxy/**` on `main`, or manually trigger **Deploy Token Proxy** from the Actions tab.

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `deploy-token-proxy.yml` | Push to `azure/token-proxy/**` or manual | Validate → Deploy → Smoke test |
| `provision-azure.yml` | Manual only | Create RG, storage, Function App, app settings |

## Security model

- **No stored Azure secrets**: OIDC federated credentials only. Tokens are scoped per-run, 5-minute lifetime.
- **Environment protection**: `production` environment requires approval (if configured).
- **Least privilege**: Contributor role on subscription. Can be scoped down to resource group after provisioning.
- **GitHub OAuth secrets**: `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` are only consumed by the provisioning workflow to set Azure App Settings. They never appear in deploy runs.
