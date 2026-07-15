param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Token = $env:SHELOOK_TOKEN,
    [string]$UserId = "smoke-test",
    [string]$Username = "Smoke Test",
    [ValidateSet("viewer", "operator", "admin")]
    [string]$Role = "viewer",
    [int]$ProductId = 0,
    [int]$ImageId = 0,
    [int]$ExperimentId = 0,
    [string]$SupplierId = ""
)

$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd("/")
$script:Passed = 0
$script:Failed = 0

function Invoke-SmokeRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [hashtable]$Headers = @{},
        [object]$Body = $null,
        [int[]]$ExpectedStatus = @(200)
    )

    $request = @{
        Uri             = "$BaseUrl$Path"
        Method          = $Method
        Headers         = $Headers
        UseBasicParsing = $true
        TimeoutSec      = 30
    }
    if ($null -ne $Body) {
        $request.ContentType = "application/json"
        $request.Body = $Body | ConvertTo-Json -Depth 8 -Compress
    }

    try {
        $response = Invoke-WebRequest @request
        $status = [int]$response.StatusCode
        $success = $ExpectedStatus -contains $status
        if ($success) {
            $script:Passed++
            Write-Host ("[PASS] {0,-28} {1}" -f $Name, $status) -ForegroundColor Green
        } else {
            $script:Failed++
            Write-Host ("[FAIL] {0,-28} {1}，预期 {2}" -f $Name, $status, ($ExpectedStatus -join "/")) -ForegroundColor Red
        }
        return [pscustomobject]@{
            Success = $success
            StatusCode = $status
            Content = $response.Content
        }
    } catch {
        $status = 0
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $status = [int]$_.Exception.Response.StatusCode
        }
        $script:Failed++
        Write-Host ("[FAIL] {0,-28} {1} {2}" -f $Name, $status, $_.Exception.Message) -ForegroundColor Red
        return [pscustomobject]@{
            Success = $false
            StatusCode = $status
            Content = ""
        }
    }
}

Write-Host "SheLook 只读 API smoke test" -ForegroundColor Cyan
Write-Host "目标：$BaseUrl"

Invoke-SmokeRequest -Name "health" -Method GET -Path "/api/health" | Out-Null
Invoke-SmokeRequest -Name "health-ready" -Method GET -Path "/api/health/ready" | Out-Null
Invoke-SmokeRequest -Name "auth-config" -Method GET -Path "/api/auth/config" | Out-Null

if (-not $Token) {
    $login = Invoke-SmokeRequest `
        -Name "development-login" `
        -Method POST `
        -Path "/api/auth/token" `
        -Body @{ user_id = $UserId; username = $Username; role = $Role }

    if (-not $login.Success) {
        Write-Host "当前环境不允许本地登录。请通过 -Token 或 SHELOOK_TOKEN 提供有效 OIDC/JWT token。" -ForegroundColor Yellow
        exit 1
    }
    try {
        $Token = ($login.Content | ConvertFrom-Json).access_token
    } catch {
        Write-Host "登录响应不包含有效 access_token。" -ForegroundColor Red
        exit 1
    }
}

$authHeaders = @{ Authorization = "Bearer $Token" }

$readOnlyChecks = @(
    @{ Name = "current-user"; Path = "/api/auth/me" },
    @{ Name = "products"; Path = "/api/products?page=1&page_size=5" },
    @{ Name = "experiments"; Path = "/api/experiments?limit=5" },
    @{ Name = "experiment-summary"; Path = "/api/experiments/auto/summary" },
    @{ Name = "dashboard-summary"; Path = "/api/dashboard/summary" },
    @{ Name = "dashboard-ctr"; Path = "/api/dashboard/ctr_trend?days=7" },
    @{ Name = "dashboard-market"; Path = "/api/dashboard/market_comparison" },
    @{ Name = "dashboard-style"; Path = "/api/dashboard/style_insight" },
    @{ Name = "review-queue"; Path = "/api/review/queue?limit=5" },
    @{ Name = "audit-logs"; Path = "/api/audit/logs?limit=5" },
    @{ Name = "model-versions"; Path = "/api/prediction/model-versions" },
    @{ Name = "metrics-stats"; Path = "/api/metrics/stats" },
    @{ Name = "metric-mappings"; Path = "/api/metrics/mappings" },
    @{ Name = "generation-platforms"; Path = "/api/generation/platforms" },
    @{ Name = "video-providers"; Path = "/api/video/providers" },
    @{ Name = "fairness-distribution"; Path = "/api/fairness/distribution" }
)

foreach ($check in $readOnlyChecks) {
    Invoke-SmokeRequest -Name $check.Name -Method GET -Path $check.Path -Headers $authHeaders | Out-Null
}

if ($ProductId -gt 0) {
    Invoke-SmokeRequest -Name "product-detail" -Method GET -Path "/api/products/$ProductId" -Headers $authHeaders | Out-Null
}
if ($ImageId -gt 0) {
    Invoke-SmokeRequest -Name "generation-status" -Method GET -Path "/api/generation/$ImageId/status" -Headers $authHeaders | Out-Null
    Invoke-SmokeRequest -Name "prediction-history" -Method GET -Path "/api/prediction/history/$ImageId" -Headers $authHeaders | Out-Null
}
if ($ExperimentId -gt 0) {
    Invoke-SmokeRequest -Name "experiment-detail" -Method GET -Path "/api/experiments/$ExperimentId" -Headers $authHeaders | Out-Null
    Invoke-SmokeRequest -Name "experiment-breakdown" -Method GET -Path "/api/experiments/$ExperimentId/breakdown" -Headers $authHeaders | Out-Null
}
if ($SupplierId) {
    $encodedSupplierId = [Uri]::EscapeDataString($SupplierId)
    Invoke-SmokeRequest -Name "supplier-report" -Method GET -Path "/api/supplier/report/$encodedSupplierId" -Headers $authHeaders | Out-Null
}

Write-Host ""
Write-Host "通过：$script:Passed；失败：$script:Failed" -ForegroundColor Cyan
if ($script:Failed -gt 0) {
    exit 1
}
exit 0
