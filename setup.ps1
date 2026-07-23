<#
.SYNOPSIS
    SheLook safe deployment entry point (Windows / PowerShell).

.DESCRIPTION
    Every Compose call explicitly uses .env.<environment>. The script never
    copies, overwrites, or uses the repository-root .env as deployment input.
    Demo data is opt-in, development-only, and requires a second confirmation.

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -Env dev -SeedDemo
    .\setup.ps1 -Env staging -Update
    .\setup.ps1 -Env prod -Status
#>

[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$SkipSeed,
    [switch]$SeedDemo,
    [switch]$ConfirmSeedDemo,
    [switch]$NoCache,
    [switch]$WithSDWebUI,
    [switch]$WithPgbouncer,
    [switch]$WithOps,
    [switch]$Clean,
    [switch]$Stop,
    [switch]$Restart,
    [string]$Logs,
    [switch]$Status,
    [switch]$Update,
    [switch]$Help,
    [ValidateSet("dev", "staging", "prod")]
    [string]$Env = "dev"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Write-Step { param([string]$Message) Write-Host "`n>>> $Message" -ForegroundColor Cyan }
function Write-OK { param([string]$Message) Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Err { param([string]$Message) Write-Host "  [ERROR] $Message" -ForegroundColor Red }
function Write-Info { param([string]$Message) Write-Host "  [INFO] $Message" -ForegroundColor Gray }

function Show-Usage {
    @(
        "SheLook deployment script",
        "",
        "  .\setup.ps1                         Deploy development (no demo data by default)",
        "  .\setup.ps1 -Env staging -Update    Deploy staging with immutable images",
        "  .\setup.ps1 -Env prod -Status       Show production service status",
        "  .\setup.ps1 -SeedDemo               Development only: seed demo data with confirmation",
        "  .\setup.ps1 -SeedDemo -ConfirmSeedDemo",
        "                                       Explicit non-interactive second confirmation",
        "",
        "Common options:",
        "  -SkipBuild -NoCache -WithSDWebUI -WithPgbouncer -WithOps -Clean -Stop -Restart",
        "  -Logs <service> -Status -Update -Env <dev|staging|prod>",
        "",
        "Environment files:",
        "  Uses .env.dev / .env.staging / .env.prod. A missing file is created once",
        "  from .env.<environment>.example (or .env.example); .env is never overwritten."
    ) -join [Environment]::NewLine | Write-Host
}

function Get-EnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path
    )

    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)\s*$") {
            $value = $Matches[1].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                return $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return ""
}

function Set-EnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $expression = "(?m)^\s*$([regex]::Escape($Name))\s*=.*$"
    if ($content -match $expression) {
        $content = [regex]::Replace($content, $expression, "${Name}=${Value}")
    } else {
        $content = $content.TrimEnd() + "`n${Name}=${Value}`n"
    }
    [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $Path), $content, (New-Object System.Text.UTF8Encoding($false)))
}

function New-SecretKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return (($bytes | ForEach-Object { "{0:x2}" -f $_ }) -join "")
}

function Test-UnsafeSecretValue {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    $normalized = $Value.Trim().ToLowerInvariant()
    $knownPlaceholders = @(
        "shelook", "shelook-dev", "shelook123", "shelook-dev-minio", "shelook-dev-secret",
        "shelook-dev-insecure-key-change-in-production", "password", "secret", "changeme",
        "change-me", "replace-me", "example", "test", "demo", "admin", "your-secret"
    )
    return $knownPlaceholders -contains $normalized -or
        $normalized -match "^(<.*>|\$\{.*\}|your[-_].*|.*(todo|placeholder).*)$"
}

function Test-RequiredBoolean {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][System.Collections.Generic.List[string]]$Errors
    )

    $actual = Get-EnvironmentValue -Name $Name -Path $Path
    if ($actual.Trim().ToLowerInvariant() -ne $Expected) {
        $Errors.Add("$Name must be $Expected")
    }
}

function Test-NonDevelopmentEnvironment {
    param([Parameter(Mandatory = $true)][string]$Path)

    $errors = New-Object 'System.Collections.Generic.List[string]'
    foreach ($name in @("BACKEND_IMAGE", "FRONTEND_IMAGE")) {
        $imageReference = Get-EnvironmentValue -Name $name -Path $Path
        if ($imageReference -notmatch "@sha256:[a-fA-F0-9]{64}$") {
            $errors.Add("$name must be digest-pinned (image@sha256:<64 hex characters>)")
        }
    }
    foreach ($name in @("SECRET_KEY", "INTEGRATION_CREDENTIALS_ENCRYPTION_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "MINIO_ROOT_PASSWORD", "MINIO_SECRET_KEY", "METRICS_API_KEY", "GRAFANA_ADMIN_PASSWORD")) {
        if (Test-UnsafeSecretValue (Get-EnvironmentValue -Name $name -Path $Path)) {
            $errors.Add("$name must be set and must not use a development placeholder")
        }
    }

    $corsOrigins = Get-EnvironmentValue -Name "CORS_ORIGINS" -Path $Path
    if ([string]::IsNullOrWhiteSpace($corsOrigins) -or $corsOrigins -match "(?i)(localhost|127\.0\.0\.1|example\.com|your[-_])") {
        $errors.Add("CORS_ORIGINS must contain non-development origins")
    }

    $grafanaRootUrl = Get-EnvironmentValue -Name "GRAFANA_ROOT_URL" -Path $Path
    if ($grafanaRootUrl -notmatch "^https://" -or $grafanaRootUrl -match "(?i)(localhost|127\.0\.0\.1|example\.com|your[-_])") {
        $errors.Add("GRAFANA_ROOT_URL must be a non-development HTTPS URL ending in /grafana/")
    } elseif ($grafanaRootUrl -notmatch "/grafana/$") {
        $errors.Add("GRAFANA_ROOT_URL must end in /grafana/")
    }

    Test-RequiredBoolean -Name "ENABLE_AUTH" -Expected "true" -Path $Path -Errors $errors
    Test-RequiredBoolean -Name "ALLOW_GENERATION_MOCKS" -Expected "false" -Path $Path -Errors $errors
    Test-RequiredBoolean -Name "C2PA_ENABLED" -Expected "true" -Path $Path -Errors $errors
    Test-RequiredBoolean -Name "C2PA_REQUIRED" -Expected "true" -Path $Path -Errors $errors

    if ([string]::IsNullOrWhiteSpace((Get-EnvironmentValue -Name "DATABASE_MIGRATION_URL" -Path $Path))) {
        $errors.Add("DATABASE_MIGRATION_URL must be set")
    }
    foreach ($name in @("METRICS_API_KEY_FILE", "C2PA_CERT_FILE", "C2PA_PRIVATE_KEY_FILE")) {
        $filePath = Get-EnvironmentValue -Name $name -Path $Path
        if ([string]::IsNullOrWhiteSpace($filePath)) {
            $errors.Add("$name must be set")
        } elseif (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            $errors.Add("$name must reference an existing regular file")
        }
    }

    if ($errors.Count -gt 0) {
        throw "Staging/production preflight failed: $($errors -join '; '). No secret values were printed."
    }
}

function Initialize-EnvironmentFile {
    $script:EnvFile = ".env.$Env"
    $specificTemplate = ".env.$Env.example"
    $fallbackTemplate = ".env.example"

    if (-not (Test-Path -LiteralPath $script:EnvFile)) {
        $template = if (Test-Path -LiteralPath $specificTemplate) { $specificTemplate } elseif (Test-Path -LiteralPath $fallbackTemplate) { $fallbackTemplate } else { $null }
        if (-not $template) {
            throw "Neither $specificTemplate nor $fallbackTemplate exists; cannot create an environment file."
        }
        Copy-Item -LiteralPath $template -Destination $script:EnvFile -ErrorAction Stop
        Write-Warn "Created $script:EnvFile from $template. Review its variables and secrets before deployment."
    }

    $secret = Get-EnvironmentValue -Name "SECRET_KEY" -Path $script:EnvFile
    if ([string]::IsNullOrWhiteSpace($secret)) {
        if ($Env -ne "dev") {
            throw "SECRET_KEY in $script:EnvFile cannot be empty. Set it from your secret-management system and retry."
        }
        Set-EnvironmentValue -Name "SECRET_KEY" -Value (New-SecretKey) -Path $script:EnvFile
        Write-OK "Generated SECRET_KEY only in $script:EnvFile for development."
    }

    if ($Env -in @("staging", "prod")) {
        $overlay = "docker-compose.$Env.yml"
        if (-not (Test-Path -LiteralPath $overlay)) {
            throw "Missing Compose overlay: $overlay"
        }
        Test-NonDevelopmentEnvironment -Path $script:EnvFile
    }

    $script:ComposeOptions = @("--env-file", $script:EnvFile, "-f", "docker-compose.yml")
    if ($Env -in @("staging", "prod")) {
        $script:ComposeOptions += @("-f", "docker-compose.$Env.yml")
    }
    Write-Info "Environment: $Env; Compose uses $script:EnvFile and never modifies .env."
}

function Get-ProfileArgs {
    $profileArgs = @()
    if ($WithSDWebUI) { $profileArgs += @("--profile", "sd-webui") }
    if ($WithPgbouncer) { $profileArgs += @("--profile", "pgbouncer") }
    if ($WithOps) { $profileArgs += @("--profile", "ops") }
    return $profileArgs
}

function Invoke-Compose {
    param(
        [switch]$AllowFailure,
        [Parameter(Mandatory = $true)][string[]]$ComposeArgs
    )

    & docker compose @script:ComposeOptions @ComposeArgs
    if ($LASTEXITCODE -ne 0 -and -not $AllowFailure) {
        throw "docker compose $($ComposeArgs -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Get-ServiceState {
    param([Parameter(Mandatory = $true)][string]$Service)

    # Do not pipe the native Compose command directly to Select-Object. PowerShell
    # can then replace the native exit code with -1, incorrectly classifying a
    # healthy service as not started.
    $containerIds = @(& docker compose @script:ComposeOptions ps -q $Service 2>$null)
    $composeExitCode = $LASTEXITCODE
    $containerId = if ($containerIds.Count -gt 0) { [string]$containerIds[0] } else { "" }
    if ($composeExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($containerId)) {
        return "not-started"
    }
    $state = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' ([string]$containerId).Trim() 2>$null)
    if ([string]::IsNullOrWhiteSpace($state)) { return "unknown" }
    return ([string]$state).Trim()
}

function Wait-ForServices {
    param(
        [Parameter(Mandatory = $true)][string[]]$Services,
        [int]$TimeoutSeconds = 180,
        [int]$IntervalSeconds = 5
    )

    $started = Get-Date
    do {
        $unready = @()
        foreach ($service in $Services) {
            $state = Get-ServiceState -Service $service
            if ($state -notin @("healthy", "running")) {
                $unready += "$service ($state)"
            }
        }
        if ($unready.Count -eq 0) { return }
        Start-Sleep -Seconds $IntervalSeconds
    } while (((Get-Date) - $started).TotalSeconds -lt $TimeoutSeconds)

    throw "Services were not ready within $TimeoutSeconds seconds: $($unready -join ', '). Run .\setup.ps1 -Env $Env -Logs <service>."
}

function Test-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install and start Docker Desktop."
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker is not running or the current user cannot access it." }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw "docker compose v2 is unavailable." }
}

$script:BuildServices = @(
    "backend",
    "migrate",
    "celery-worker",
    "celery-worker-generation",
    "celery-worker-analytics",
    "celery-beat",
    "flower",
    "frontend"
)
$script:CoreServices = @("postgres", "redis", "minio")
$script:CriticalApplicationServices = @(
    "backend",
    "frontend",
    "nginx",
    "celery-worker",
    "celery-worker-generation",
    "celery-worker-analytics",
    "celery-beat"
)

function Prepare-Images {
    if ($SkipBuild) {
        Write-Info "Skipping image preparation (-SkipBuild); local images will be used."
        return
    }

    if ($Env -eq "dev") {
        $buildArgs = @("build", "--build-arg", "BUILDKIT_INLINE_CACHE=1")
        if ($NoCache) { $buildArgs += "--no-cache" }
        $buildArgs += $script:BuildServices
        Write-Step "Build development images (API, migration, all workers, frontend)"
        Invoke-Compose -ComposeArgs $buildArgs
        return
    }

    if ($NoCache) { Write-Warn "-NoCache applies only to development builds and is ignored in $Env." }
    Write-Step "Pull $Env immutable images (API, migration, all workers, frontend)"
    Invoke-Compose -ComposeArgs (@("pull") + $script:BuildServices)
}

function Run-Migrations {
    Write-Step "Run database migrations (dedicated migrate service)"
    Invoke-Compose -ComposeArgs @("--profile", "migration", "run", "--rm", "migrate")
    Write-OK "Database migrations completed at Alembic head."
}

function Initialize-ObjectStorage {
    Write-Step "Initialize object storage"
    Invoke-Compose -ComposeArgs @("run", "--rm", "--no-deps", "backend", "python", "scripts/init_minio.py")
    Write-OK "MinIO buckets are ready."
}

function Confirm-DemoSeed {
    if (-not $SeedDemo) {
        Write-Info "Demo data is disabled by default. Use -SeedDemo only in development."
        return $false
    }
    if ($Env -ne "dev") {
        Write-Warn "Demo seeding is forbidden in $Env and has been skipped."
        return $false
    }
    if ($SkipSeed) { throw "-SeedDemo and -SkipSeed cannot be used together." }
    if ($ConfirmSeedDemo) { return $true }

    Write-Warn "Demo data writes to the current development database; do not use it with business data."
    $confirmation = Read-Host "Type SEED-DEMO to confirm demo-data seeding"
    if ($confirmation -ne "SEED-DEMO") {
        throw "The second confirmation was not completed; demo-data seeding was cancelled."
    }
    return $true
}

function Seed-DemoData {
    if (-not (Confirm-DemoSeed)) { return }
    Write-Step "Seed development demo data"
    Invoke-Compose -ComposeArgs @("run", "--rm", "--no-deps", "backend", "python", "-m", "scripts.seed_data")
    Write-OK "Development demo data has been seeded."
}

function Start-Platform {
    param([switch]$ForceRecreate)

    Write-Step "Start core services"
    Invoke-Compose -ComposeArgs (@("up", "-d") + $script:CoreServices)
    Wait-ForServices -Services $script:CoreServices -TimeoutSeconds 120 -IntervalSeconds 3
    Write-OK "PostgreSQL, Redis, and MinIO are ready."

    Run-Migrations
    Initialize-ObjectStorage
    Seed-DemoData

    Write-Step "Start application services"
    $upArgs = (Get-ProfileArgs) + @("up", "-d", "--remove-orphans")
    if ($ForceRecreate) { $upArgs += "--force-recreate" }
    Invoke-Compose -ComposeArgs $upArgs
    Wait-ForServices -Services $script:CriticalApplicationServices -TimeoutSeconds 240 -IntervalSeconds 5
    Write-OK "Critical application services are ready."
}

function Show-Summary {
    Write-Step "Deployment status"
    Invoke-Compose -ComposeArgs @("ps")
    $defaultPort = if ($Env -eq "staging") { "8080" } else { "80" }
    $nginxPort = Get-EnvironmentValue -Name "NGINX_PORT" -Path $script:EnvFile
    if ([string]::IsNullOrWhiteSpace($nginxPort)) { $nginxPort = $defaultPort }
    $healthUrl = if ($nginxPort -eq "80") {
        "http://localhost/api/health"
    } else {
        "http://localhost:$nginxPort/api/health"
    }
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -Method Get -TimeoutSec 10 -UseBasicParsing
        if ($response.StatusCode -eq 200) { Write-OK "Health check passed: $healthUrl" }
    } catch {
        Write-Warn "The local reverse-proxy health check failed; inspect -Logs nginx or -Logs backend."
    }
    Write-Host "`nCommon actions:" -ForegroundColor White
    Write-Host "  .\setup.ps1 -Env $Env -Status" -ForegroundColor DarkGray
    Write-Host "  .\setup.ps1 -Env $Env -Logs backend" -ForegroundColor DarkGray
    Write-Host "  .\setup.ps1 -Env $Env -Stop" -ForegroundColor DarkGray
}

try {
    if ($Help -or $args -contains "-?" -or $args -contains "--help") {
        Show-Usage
        exit 0
    }
    Initialize-EnvironmentFile
    Test-Docker

    if ($Status) {
        $statusArgs = (Get-ProfileArgs) + @("ps")
        Invoke-Compose -ComposeArgs $statusArgs
        exit 0
    }
    if ($Logs) {
        Invoke-Compose -ComposeArgs @("logs", "-f", $Logs)
        exit 0
    }
    if ($Stop) {
        Write-Step "Stop $Env services"
        $stopArgs = (Get-ProfileArgs) + @("down")
        Invoke-Compose -AllowFailure -ComposeArgs $stopArgs
        Write-OK "Services stopped; volumes were preserved."
        exit 0
    }
    if ($Clean) {
        Write-Warn "-Clean removes data volumes for the $Env Compose project."
        $cleanArgs = (Get-ProfileArgs) + @("down", "-v", "--remove-orphans")
        Invoke-Compose -AllowFailure -ComposeArgs $cleanArgs
        Write-OK "Containers and volumes were removed."
    }
    if ($Restart) {
        Write-Step "Restart $Env (migrate first, then recreate application containers)"
        Start-Platform -ForceRecreate
        Show-Summary
        exit 0
    }

    Prepare-Images
    if ($Update) {
        Write-Info "-Update deploys the current working tree or already-pulled images; it never runs git pull."
    }
    Start-Platform
    Show-Summary
} catch {
    Write-Err $_.Exception.Message
    exit 1
}
