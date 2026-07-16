<#
SheLook 一键部署脚本 — Windows 版

干的事情：端口检测、Docker 检查、.env 配置、镜像构建、
基础服务启动、数据库迁移、MinIO 初始化、演示数据、全部启动 + 健康检查。

常用命令（懒人版）：
  .\setup.ps1                    # 全新部署
  .\setup.ps1 -SkipBuild         # 跳过构建（用已有镜像）
  .\setup.ps1 -SkipSeed          # 跳过演示数据
  .\setup.ps1 -NoCache           # 无缓存重新 build
  .\setup.ps1 -WithSDWebUI       # 开本地 SD 生图（要 GPU）
  .\setup.ps1 -WithPgbouncer     # 开 PgBouncer 连接池
  .\setup.ps1 -Clean             # 清干净重来（会删数据卷！）
  .\setup.ps1 -Stop              # 只停服务
  .\setup.ps1 -Restart           # 重启（不重新 build）
  .\setup.ps1 -Logs backend      # 看某个服务的日志
  .\setup.ps1 -Status            # 看状态
  .\setup.ps1 -Update            # git pull + build + 重启（保留数据）
  .\setup.ps1 -Env staging       # 指定环境，自动加载覆盖 compose 文件
#>

param(
    [switch]$SkipBuild,
    [switch]$SkipSeed,
    [switch]$NoCache,
    [switch]$WithSDWebUI,
    [switch]$WithPgbouncer,
    [switch]$Clean,
    [switch]$Stop,
    [switch]$Restart,
    [string]$Logs,
    [switch]$Status,
    [switch]$Update,
    [ValidateSet("dev", "staging", "prod")]
    [string]$Env = ""
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$script:ComposeFiles = @("-f", "docker-compose.yml")

# 多环境配置：选择私有环境文件，并为 staging / prod 加载覆盖配置
if ($Env) {
    $envFile = ".env.$Env"
    if (-not (Test-Path $envFile)) {
        if (-not (Test-Path ".env.example")) {
            Write-Host "  [ERROR] .env.example 不存在" -ForegroundColor Red
            exit 1
        }
        Copy-Item ".env.example" $envFile
        if ($Env -ne "dev") {
            Write-Host "  [ENV] 已创建 $envFile，请补齐该环境的密钥后重新执行" -ForegroundColor Yellow
            exit 1
        }
        Write-Host "  [ENV] 已从 .env.example 创建 $envFile" -ForegroundColor Yellow
    }
    Copy-Item $envFile ".env" -Force
    Write-Host "  [ENV] 已从 $envFile 复制到 .env" -ForegroundColor Cyan

    if ($Env -in @("staging", "prod")) {
        $overlay = "docker-compose.$Env.yml"
        if (-not (Test-Path $overlay)) {
            Write-Host "  [ERROR] Compose 覆盖文件 $overlay 不存在" -ForegroundColor Red
            exit 1
        }
        $script:ComposeFiles += @("-f", $overlay)
    }
}

# 输出辅助 —— 懒得每次手写颜色代码
function Write-Step { param([string]$Message) Write-Host "`n>>> $Message" -ForegroundColor Cyan }
function Write-OK   { param([string]$Message) Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Err  { param([string]$Message) Write-Host "  [ERROR] $Message" -ForegroundColor Red }
function Write-Info { param([string]$Message) Write-Host "  [INFO] $Message" -ForegroundColor Gray }
function Write-Dot  { param([string]$Message) Write-Host "  ..     $Message" -ForegroundColor DarkGray }

# 构建 profile 参数（按需拼接 --profile 选项）
function Get-ProfileArgs {
    $args = @()
    if ($WithSDWebUI)   { $args += "--profile", "sd-webui" }
    if ($WithPgbouncer) { $args += "--profile", "pgbouncer" }
    return $args
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArgs)
    & docker compose @script:ComposeFiles @ComposeArgs
}

# 等健康检查 —— 轮询 docker inspect 到超时
function Wait-Healthy {
    param(
        [string[]]$Services,
        [int]$MaxWait = 120,
        [int]$Interval = 5
    )
    $started = Get-Date
    do {
        Start-Sleep -Seconds $Interval
        $allHealthy = $true
        foreach ($svc in $Services) {
            $status = docker inspect --format '{{.State.Health.Status}}' $svc 2>$null
            if ($status -ne "healthy") {
                $allHealthy = $false
                break
            }
        }
        if ($allHealthy) { break }
        $elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 0)
        Write-Dot "等待健康检查... (${elapsed}s / ${MaxWait}s)"
    } while ($elapsed -lt $MaxWait)

    if (-not $allHealthy) {
        $unhealthy = @()
        foreach ($svc in $Services) {
            $status = docker inspect --format '{{.State.Health.Status}}' $svc 2>$null
            if ($status -ne "healthy") { $unhealthy += "$svc ($status)" }
        }
        return $false, $unhealthy
    }
    return $true, @()
}

# 检测端口有没有被占
function Test-Ports {
    $ports = @{
        80   = "Nginx"
        3000 = "Frontend"
        8000 = "Backend"
        5432 = "PostgreSQL"
        6379 = "Redis"
        9000 = "MinIO API"
        9001 = "MinIO Console"
        5555 = "Flower"
    }
    $conflicts = @()
    foreach ($port in $ports.Keys) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $procName = ""
            try {
                $proc = Get-Process -Id $conn[0].OwningProcess -ErrorAction Stop
                $procName = $proc.ProcessName
            } catch {}
            $conflicts += "Port ${port} ($($ports[$port])) -> PID $($conn[0].OwningProcess) ($procName)"
        }
    }
    return $conflicts
}

# 检测磁盘空间
function Test-DiskSpace {
    param([int]$MinGB = 10)
    $drive = (Get-Location).Drive.Name
    $free = (Get-PSDrive -Name $drive).Free
    $freeGB = [math]::Round($free / 1GB, 1)
    if ($freeGB -lt $MinGB) {
        return $false, $freeGB
    }
    return $true, $freeGB
}

# ---- 子命令模式 ----
# --Status
if ($Status) {
    Write-Step "服务运行状态"
    $composeArgs = @("compose") + $script:ComposeFiles + (Get-ProfileArgs) + @("ps", "--format", "table")
    & docker @composeArgs
    exit $LASTEXITCODE
}

# --Logs
if ($Logs) {
    Write-Host "`n>>> 跟踪 $Logs 日志 (Ctrl+C 退出)`n" -ForegroundColor Cyan
    Invoke-Compose logs -f $Logs
    exit $LASTEXITCODE
}

# --Stop
if ($Stop) {
    Write-Step "停止所有 SheLook 服务..."
    $composeArgs = @("compose") + $script:ComposeFiles + (Get-ProfileArgs) + @("down")
    & docker @composeArgs 2>$null
    Write-OK "所有服务已停止"
    exit 0
}

# --Restart
if ($Restart) {
    Write-Step "重启全部服务..."
    $profileArgs = Get-ProfileArgs
    Invoke-Compose down 2>$null
    $composeArgs = @("compose") + $script:ComposeFiles + $profileArgs + @("up", "-d")
    & docker @composeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Err "重启失败"
        exit 1
    }
    Write-OK "服务已重启"
    Invoke-Compose ps
    exit 0
}

# --Update
if ($Update) {
    Write-Step "更新部署 (保留数据)"

    # 1. 重新构建镜像
    Write-Info "重新构建镜像..."
    $buildArgs = @("compose") + $script:ComposeFiles + @("build")
    if ($NoCache) { $buildArgs += "--no-cache" }
    $buildArgs += "backend", "celery-worker", "frontend"
    & docker @buildArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Err "镜像构建失败"
        exit 1
    }
    Write-OK "镜像构建完成"

    # 2. 重启服务
    $profileArgs = Get-ProfileArgs
    $composeArgs = @("compose") + $script:ComposeFiles + $profileArgs + @("up", "-d")
    & docker @composeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Err "服务启动失败"
        exit 1
    }

    # 3. 运行迁移
    Write-Info "执行数据库迁移..."
    Invoke-Compose run --rm backend alembic upgrade head 2>$null
    Write-OK "数据库迁移完成"

    Write-OK "更新部署完成"
    Invoke-Compose ps
    exit 0
}

# ==== 1/9  环境检查 ====
Write-Step "1/9  环境检查"

# Docker 运行状态
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Docker 未运行或未安装"
    Write-Info "请先启动 Docker Desktop: https://www.docker.com/products/docker-desktop"
    exit 1
}
$dockerVersion = docker version --format '{{.Server.Version}}' 2>$null
Write-OK "Docker 引擎运行正常 (v$dockerVersion)"

# docker compose 可用性
$composeVer = docker compose version --short 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose 不可用，请升级 Docker Desktop"
    exit 1
}
Write-OK "docker compose v$composeVer"

# 磁盘空间
$spaceOk, $freeGB = Test-DiskSpace -MinGB 10
if (-not $spaceOk) {
    Write-Warn "磁盘剩余空间不足: ${freeGB}GB (建议 >= 10GB)"
    Write-Info "构建镜像 + CLIP 模型下载 + 演示数据约需 8GB"
} else {
    Write-OK "磁盘空间充足 (${freeGB}GB 可用)"
}

# 端口占用检测
$portConflicts = Test-Ports
if ($portConflicts.Count -gt 0) {
    Write-Warn "检测到端口被占用:"
    foreach ($c in $portConflicts) {
        Write-Info "  $c"
    }
    Write-Info "如为 SheLook 自身容器可忽略；如为其他进程请先释放端口"
} else {
    Write-OK "所需端口均无冲突"
}

# --Clean 模式
if ($Clean) {
    Write-Step "清理现有部署..."
    $profileArgs = Get-ProfileArgs
    $composeArgs = @("compose") + $script:ComposeFiles + $profileArgs + @("down", "-v")
    & docker @composeArgs 2>$null
    Write-OK "已清理所有容器和数据卷"
}

# ==== 2/9  .env 配置 ====
Write-Step "2/9  .env 配置"

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-OK "已从 .env.example 创建 .env"
    } else {
        Write-Err ".env.example 不存在"
        exit 1
    }
} else {
    Write-OK ".env 文件已存在"
}

$envContent = Get-Content ".env" -Raw -Encoding UTF8

# 自动生成 SECRET_KEY
if ($envContent -match '(?m)^SECRET_KEY=\s*$') {
    $secretKey = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Minimum 0 -Maximum 16) })
    $envContent = $envContent -replace '(?m)^SECRET_KEY=\s*$', "SECRET_KEY=$secretKey"
    [System.IO.File]::WriteAllText("$ScriptDir\.env", $envContent, [System.Text.UTF8Encoding]::new($false))
    Write-OK "SECRET_KEY 已自动生成 (64 位 hex)"
} elseif ($envContent -match '(?m)^SECRET_KEY=(\S+)$') {
    $keyLen = $Matches[1].Length
    if ($keyLen -lt 16) {
        Write-Warn "SECRET_KEY 过短 ($keyLen 字符)，建议 >= 32 字符"
    } else {
        Write-OK "SECRET_KEY 已配置 ($keyLen 字符)"
    }
} else {
    $secretKey = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Minimum 0 -Maximum 16) })
    $envContent = $envContent.TrimEnd() + "`nSECRET_KEY=$secretKey`n"
    [System.IO.File]::WriteAllText("$ScriptDir\.env", $envContent, [System.Text.UTF8Encoding]::new($false))
    Write-OK "SECRET_KEY 已自动生成并追加到 .env"
}

# 检查 API Key
$requiredKeys = @{
    "GEMINI_API_KEY"      = "Gemini (标签提取 / AI 审核 / 促销图生成)"
    "REPLICATE_API_TOKEN" = "Replicate (FLUX.2 Pro 生图)"
}
$missingKeys = @()
foreach ($key in $requiredKeys.Keys) {
    if ($envContent -match "(?m)^$key=\s*$") {
        $missingKeys += "[$key] $($requiredKeys[$key])"
    }
}
if ($missingKeys.Count -gt 0) {
    Write-Warn "以下 API Key 未配置，相关功能将降级:"
    foreach ($mk in $missingKeys) { Write-Info "  $mk" }
} else {
    Write-OK "推荐 API Key 已配置"
}

# 可选视频 Key
$optionalKeys = @{
    "KLING_API_KEY"    = "Kling AI (视频生成主通道)"
    "RUNWAY_API_KEY"   = "Runway Gen-4.5 (视频降级)"
}
foreach ($key in $optionalKeys.Keys) {
    if ($envContent -match "(?m)^$key=\s*$") {
        Write-Dot "可选: [$key] $($optionalKeys[$key]) 未配置"
    }
}

# ==== 3/9  构建 Docker 镜像 ====
Write-Step "3/9  构建 Docker 镜像"

if ($SkipBuild) {
    Write-OK "跳过镜像构建 (--SkipBuild)"
} else {
    $buildArgs = @("compose") + $script:ComposeFiles + @("build", "--build-arg", "BUILDKIT_INLINE_CACHE=1")
    if ($NoCache) { $buildArgs += "--no-cache" }
    $buildArgs += "backend", "celery-worker", "frontend"
    Write-Info "正在构建镜像 (backend / celery / frontend)..."
    if ($NoCache) { Write-Dot "使用 --no-cache，构建时间较长" }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & docker @buildArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Err "镜像构建失败，请检查构建日志"
        Write-Info "常见原因: 网络超时 / 磁盘空间不足 / Dockerfile 语法错误"
        exit 1
    }
    $sw.Stop()
    $buildSec = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    $buildMin = [math]::Floor($buildSec / 60)
    $buildRem = [math]::Round($buildSec % 60, 1)
    Write-OK "镜像构建完成 (耗时 ${buildMin}m ${buildRem}s)"
}

# ==== 4/9  启动基础服务 (PostgreSQL / Redis / MinIO) ====
Write-Step "4/9  启动基础服务 (PostgreSQL / Redis / MinIO)"

Invoke-Compose up -d postgres redis minio
if ($LASTEXITCODE -ne 0) {
    Write-Err "基础服务启动失败"
    exit 1
}
Write-OK "基础服务容器已创建"

# 等待健康
Write-Info "等待基础服务健康检查..."
$ok, $unhealthy = Wait-Healthy -Services @(
    "shelook-postgres", "shelook-redis", "shelook-minio"
) -MaxWait 90 -Interval 3

if (-not $ok) {
    Write-Err "基础服务未就绪: $($unhealthy -join ', ')"
    Write-Info "排查: docker compose logs postgres redis minio"
    exit 1
}
Write-OK "PostgreSQL / Redis / MinIO 全部健康"

# ==== 5/9  数据库迁移 ====
Write-Step "5/9  数据库迁移 (Alembic)"

Write-Info "执行 alembic upgrade head..."
Invoke-Compose run --rm backend alembic upgrade head 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Err "数据库迁移失败"
    Write-Info "排查: docker compose run --rm backend alembic history"
    exit 1
}
Write-OK "数据库迁移完成 (6 个版本已应用)"

# ==== 6/9  MinIO 初始化 ====
Write-Step "6/9  MinIO 存储初始化"

Invoke-Compose run --rm backend python scripts/init_minio.py 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warn "MinIO 初始化失败 (可忽略，bucket 可能已存在)"
} else {
    Write-OK "MinIO 存储桶已就绪 (product-images)"
}

# ==== 7/9  演示数据 ====
Write-Step "7/9  演示数据填充"

if ($SkipSeed) {
    Write-OK "跳过演示数据填充 (--SkipSeed)"
} else {
    Write-Info "正在填充 Mock 演示数据..."
    Invoke-Compose run --rm backend python scripts/seed_data.py
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "演示数据填充失败 (不影响核心功能)"
    } else {
        Write-OK "Mock 演示数据已填充"
    }
}

# ==== 8/9  启动全部应用服务 ====
Write-Step "8/9  启动全部应用服务"

$profileArgs = Get-ProfileArgs
if ($profileArgs.Count -gt 0) {
    Write-Info "Profile: $($profileArgs -join ' ')"
}

$composeArgs = @("compose") + $script:ComposeFiles + $profileArgs + @("up", "-d")
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Err "应用服务启动失败"
    exit 1
}
Write-OK "应用服务容器已创建"

# 等待应用健康
Write-Info "等待应用服务健康就绪..."
$appServices = @(
    "shelook-backend",
    "shelook-frontend",
    "shelook-nginx",
    "shelook-celery-worker",
    "shelook-celery-beat",
    "shelook-flower"
    "shelook-prometheus"
    "shelook-grafana"
)
$ok, $unhealthy = Wait-Healthy -Services $appServices -MaxWait 180 -Interval 5

if (-not $ok) {
    Write-Warn "部分服务未就绪: $($unhealthy -join ', ')"
    Write-Info "可能原因: CLIP 模型首次下载较慢 / Celery worker 启动中"
    Write-Info "排查: docker compose ps ; docker compose logs <服务名>"
} else {
    Write-OK "全部应用服务健康就绪"
}

# ==== 9/9  验证 & 汇总 ====
Write-Step "9/9  验证与汇总"

# 后端 API 验证
$apiOk = $false
try {
    $healthResp = Invoke-RestMethod -Uri "http://localhost:8000/api/health" -Method Get -TimeoutSec 15
    Write-OK "后端 API 响应正常: $($healthResp | ConvertTo-Json -Compress)"
    $apiOk = $true
} catch {
    Write-Warn "后端 API 暂未响应: $_"
    Write-Info "可能仍在初始化，稍后重试: curl http://localhost:8000/api/health"
}

# 前端验证
try {
    $feResp = Invoke-WebRequest -Uri "http://localhost:3000" -Method Head -TimeoutSec 10 -UseBasicParsing
    if ($feResp.StatusCode -eq 200) {
        Write-OK "前端应用响应正常"
    }
} catch {
    Write-Warn "前端应用暂未响应"
}

# Nginx 验证
try {
    $ngxResp = Invoke-WebRequest -Uri "http://localhost" -Method Head -TimeoutSec 10 -UseBasicParsing
    if ($ngxResp.StatusCode -eq 200) {
        Write-OK "Nginx 反向代理正常"
    }
} catch {
    Write-Warn "Nginx 暂未响应"
}

# 服务状态表
Write-Host ""
Write-Host "  服务状态一览:" -ForegroundColor White
$allServices = @(
    @{ Name="PostgreSQL";    Container="shelook-postgres";       Port="5432";  Url="" },
    @{ Name="Redis";          Container="shelook-redis";          Port="6379";  Url="" },
    @{ Name="MinIO";          Container="shelook-minio";          Port="9000";  Url="http://localhost:9001" },
    @{ Name="Backend (FastAPI)"; Container="shelook-backend";     Port="8000";  Url="http://localhost:8000/docs" },
    @{ Name="Celery Worker";  Container="shelook-celery-worker";  Port="";      Url="" },
    @{ Name="Celery Beat";    Container="shelook-celery-beat";    Port="";      Url="" },
    @{ Name="Flower";         Container="shelook-flower";         Port="5555";  Url="http://localhost:5555/flower" },
    @{ Name="Frontend (Next.js)"; Container="shelook-frontend";   Port="3000";  Url="http://localhost:3000" },
    @{ Name="Nginx";          Container="shelook-nginx";           Port="80";    Url="http://localhost" }
    @{ Name="Prometheus";     Container="shelook-prometheus";      Port="9090";  Url="http://localhost:9090" },
    @{ Name="Grafana";        Container="shelook-grafana";         Port="3001";  Url="http://localhost/grafana/" }
)
foreach ($svc in $allServices) {
    $containerName = $svc.Container
    # 注意：不能用 $status 作为变量名 —— 它与脚本参数 [switch]$Status 冲突
    # (PowerShell 变量名不区分大小写)，赋字符串值会触发 SwitchParameter 转换错误
    $svcStatus = "unknown"
    $inspectJson = docker inspect $containerName 2>$null | Out-String
    if ($inspectJson) {
        try {
            $obj = $inspectJson | ConvertFrom-Json
            if ($obj.State.Health) {
                $svcStatus = [string]$obj.State.Health.Status
            } else {
                $svcStatus = [string]$obj.State.Status
            }
        } catch {
            $svcStatus = "parse-error"
        }
    } else {
        $svcStatus = "not-found"
    }
    $statusColor = if ($svcStatus -eq "healthy" -or $svcStatus -eq "running") { "Green" } else { "Yellow" }
    $portStr = if ($svc.Port) { ":$($svc.Port)" } else { "     " }
    $urlStr = if ($svc.Url) { $svc.Url } else { "" }
    Write-Host ("  [$svcStatus] ".PadRight(12)) -NoNewline -ForegroundColor $statusColor
    Write-Host ($svc.Name.PadRight(22)) -NoNewline
    Write-Host ($portStr.PadRight(8)) -NoNewline -ForegroundColor DarkGray
    Write-Host $urlStr -ForegroundColor Cyan
}

# ==== 完成 ====
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SheLook 部署完成!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  访问地址:" -ForegroundColor White
Write-Host "    统一入口 (Nginx)     http://localhost" -ForegroundColor Cyan
Write-Host "    前端应用              http://localhost:3000" -ForegroundColor Cyan
Write-Host "    后端 Swagger          http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "    MinIO 控制台          http://localhost:9001" -ForegroundColor Cyan
Write-Host "    Flower 任务监控       http://localhost:5555/flower" -ForegroundColor Cyan
Write-Host "    Prometheus            http://localhost:9090" -ForegroundColor Cyan
Write-Host "    Grafana               http://localhost/grafana/" -ForegroundColor Cyan
Write-Host ""
Write-Host "  常用命令:" -ForegroundColor White
Write-Host "    查看状态    .\setup.ps1 -Status" -ForegroundColor Gray
Write-Host "    查看日志    .\setup.ps1 -Logs backend" -ForegroundColor Gray
Write-Host "    重启服务    .\setup.ps1 -Restart" -ForegroundColor Gray
Write-Host "    停止服务    .\setup.ps1 -Stop" -ForegroundColor Gray
Write-Host "    更新部署    .\setup.ps1 -Update" -ForegroundColor Gray
Write-Host ""
