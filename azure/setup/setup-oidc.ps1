# ─────────────────────────────────────────────────────────────
# OIDC Setup: Entra ID → GitHub Actions federation
# ─────────────────────────────────────────────────────────────
# Run this ONCE from your local machine to create:
#   1. Entra app registration (service principal)
#   2. Federated credential for GitHub Actions OIDC
#   3. Role assignment (Contributor on the subscription)
#
# After running, add these as GitHub repo secrets:
#   AZURE_CLIENT_ID
#   AZURE_TENANT_ID
#   AZURE_SUBSCRIPTION_ID
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Sufficient Entra permissions to create app registrations
#   - Owner or User Access Admin on the subscription
# ─────────────────────────────────────────────────────────────

# ── Configuration ─────────────────────────────────────────
$SUBSCRIPTION_ID  = "835a9ee3-aef1-4ebb-a98f-6bc9b7886a7f"
$GITHUB_ORG       = "CodeGamified"             # GitHub org or username
$GITHUB_REPO      = "codegamified.github.io"   # Repo name
$APP_NAME          = "codegamified-github-actions"  # Entra app display name
$ENVIRONMENT       = "production"              # GitHub environment name (must match workflow)

Write-Host "`n═══ CodeGamified — OIDC Setup ═══`n" -ForegroundColor Cyan

# ── Step 1: Create Entra app registration ────────────────
Write-Host "[1/5] Creating Entra app registration: $APP_NAME" -ForegroundColor Yellow

$existing = az ad app list --display-name $APP_NAME --query "[0].appId" -o tsv 2>$null
if ($existing) {
    Write-Host "  App already exists: $existing" -ForegroundColor Gray
    $CLIENT_ID = $existing
} else {
    $CLIENT_ID = az ad app create --display-name $APP_NAME --query appId -o tsv
    Write-Host "  Created app: $CLIENT_ID" -ForegroundColor Green
}

# ── Step 2: Create service principal ─────────────────────
Write-Host "[2/5] Creating service principal" -ForegroundColor Yellow

$spExists = az ad sp show --id $CLIENT_ID --query id -o tsv 2>$null
if ($spExists) {
    Write-Host "  Service principal exists" -ForegroundColor Gray
    $SP_OBJECT_ID = $spExists
} else {
    $SP_OBJECT_ID = az ad sp create --id $CLIENT_ID --query id -o tsv
    Write-Host "  Created SP: $SP_OBJECT_ID" -ForegroundColor Green
}

# ── Step 3: Add federated credential ────────────────────
Write-Host "[3/5] Adding federated credential for GitHub Actions OIDC" -ForegroundColor Yellow

# Credential for the 'production' environment (deploy + provision workflows)
# NOTE: Write to temp file — PowerShell pipe + ConvertTo-Json mangles quotes for az CLI
$fedCredEnv = @{
    name        = "github-actions-$GITHUB_REPO-env-production"
    issuer      = "https://token.actions.githubusercontent.com"
    subject     = "repo:${GITHUB_ORG}/${GITHUB_REPO}:environment:${ENVIRONMENT}"
    description = "GitHub Actions OIDC — $GITHUB_REPO environment:production"
    audiences   = @("api://AzureADTokenExchange")
} | ConvertTo-Json
$fedCredEnvFile = [System.IO.Path]::GetTempFileName()
$fedCredEnv | Set-Content -Path $fedCredEnvFile -Encoding utf8

$fedCredExists = az ad app federated-credential list --id $CLIENT_ID --query "[?name=='github-actions-$GITHUB_REPO-env-production'].name" -o tsv 2>$null
if ($fedCredExists) {
    Write-Host "  Federated credential (environment) already exists" -ForegroundColor Gray
} else {
    az ad app federated-credential create --id $CLIENT_ID --parameters "@$fedCredEnvFile" | Out-Null
    Write-Host "  Created federated credential (environment:production)" -ForegroundColor Green
}
Remove-Item $fedCredEnvFile -ErrorAction SilentlyContinue

# Also add credential for main branch (for validate job which doesn't use environment)
$fedCredBranch = @{
    name        = "github-actions-$GITHUB_REPO-ref-main"
    issuer      = "https://token.actions.githubusercontent.com"
    subject     = "repo:${GITHUB_ORG}/${GITHUB_REPO}:ref:refs/heads/main"
    description = "GitHub Actions OIDC — $GITHUB_REPO branch:main"
    audiences   = @("api://AzureADTokenExchange")
} | ConvertTo-Json
$fedCredBranchFile = [System.IO.Path]::GetTempFileName()
$fedCredBranch | Set-Content -Path $fedCredBranchFile -Encoding utf8

$fedCredBranchExists = az ad app federated-credential list --id $CLIENT_ID --query "[?name=='github-actions-$GITHUB_REPO-ref-main'].name" -o tsv 2>$null
if ($fedCredBranchExists) {
    Write-Host "  Federated credential (branch) already exists" -ForegroundColor Gray
} else {
    az ad app federated-credential create --id $CLIENT_ID --parameters "@$fedCredBranchFile" | Out-Null
    Write-Host "  Created federated credential (ref:main)" -ForegroundColor Green
}
Remove-Item $fedCredBranchFile -ErrorAction SilentlyContinue

# ── Step 4: Role assignment ──────────────────────────────
Write-Host "[4/5] Assigning Contributor role on subscription" -ForegroundColor Yellow

$roleExists = az role assignment list --assignee $CLIENT_ID --scope "/subscriptions/$SUBSCRIPTION_ID" --role Contributor --query "[0].id" -o tsv 2>$null
if ($roleExists) {
    Write-Host "  Role assignment exists" -ForegroundColor Gray
} else {
    az role assignment create `
        --assignee $CLIENT_ID `
        --role Contributor `
        --scope "/subscriptions/$SUBSCRIPTION_ID" | Out-Null
    Write-Host "  Assigned Contributor" -ForegroundColor Green
}

# ── Step 5: Output ───────────────────────────────────────
$TENANT_ID = az account show --query tenantId -o tsv

Write-Host "`n[5/5] Done! Add these as GitHub repo secrets:" -ForegroundColor Yellow
Write-Host "  ┌──────────────────────────────────────────────────────┐" -ForegroundColor DarkGray
Write-Host "  │  AZURE_CLIENT_ID        = $CLIENT_ID" -ForegroundColor White
Write-Host "  │  AZURE_TENANT_ID        = $TENANT_ID" -ForegroundColor White
Write-Host "  │  AZURE_SUBSCRIPTION_ID  = $SUBSCRIPTION_ID" -ForegroundColor White
Write-Host "  └──────────────────────────────────────────────────────┘" -ForegroundColor DarkGray

Write-Host "`n  Also add these for the provisioning workflow:" -ForegroundColor Yellow
Write-Host "  ┌──────────────────────────────────────────────────────┐" -ForegroundColor DarkGray
Write-Host "  │  OAUTH_CLIENT_ID     = <from GitHub OAuth App>" -ForegroundColor White
Write-Host "  │  OAUTH_CLIENT_SECRET = <from GitHub OAuth App>" -ForegroundColor White
Write-Host "  └──────────────────────────────────────────────────────┘" -ForegroundColor DarkGray

Write-Host "`n  GitHub repo settings URL:" -ForegroundColor Gray
Write-Host "  https://github.com/$GITHUB_ORG/$GITHUB_REPO/settings/secrets/actions`n" -ForegroundColor Cyan

Write-Host "  Also create a 'production' environment at:" -ForegroundColor Gray
Write-Host "  https://github.com/$GITHUB_ORG/$GITHUB_REPO/settings/environments`n" -ForegroundColor Cyan
