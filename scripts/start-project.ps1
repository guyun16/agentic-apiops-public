[CmdletBinding()]
param([switch]$Stop, [switch]$Restart, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo '.local-run'
$stateFile = Join-Path $runtime 'processes.json'
$coreScript = Join-Path $PSScriptRoot 'stage21_start_live_services.ps1'
$coreState = Join-Path $env:TEMP 'agentic-apiops-stage21-live/current-runtime-state.json'
$consoleUrl = 'http://127.0.0.1:5173'
$managed = @()
$ownsCore = $false
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
# An open file handle also releases the lock if the launcher crashes.
try { $lock = [IO.File]::Open((Join-Path $runtime 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
catch { Write-Host 'Another launcher is running. Please wait for it to finish.'; exit 1 }

function Save-State {
    @{ Services = @($script:managed); OwnsCore = $script:ownsCore } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $stateFile -Encoding UTF8
}

function Invoke-Core([switch]$Cleanup) {
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $coreScript + '"'))
    $logName = 'core-start.log'
    if ($Cleanup) { $arguments += '-Cleanup'; $logName = 'stop-core.log' }
    # Wait for the launcher itself, not the background services inheriting its pipes.
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime $logName) -RedirectStandardError (Join-Path $runtime "$logName.stderr.log")
    $null = $process.Handle # Preserve the native exit code in Windows PowerShell 5.1.
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Core operation failed. See $runtime\$logName and its stderr log." }
}

function Get-OwnedProcess($entry) {
    $process = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$entry.StartTicks) {
        throw "PID $($entry.Id) was reused; refusing to stop an unrelated process."
    }
    return $process
}

function Stop-Applications {
    foreach ($entry in $script:managed) {
        $process = Get-OwnedProcess $entry
        if ($null -ne $process) { $process | Stop-Process -Force }
    }
    $script:managed = @()
    if ($script:ownsCore -and (Test-Path -LiteralPath $coreState)) {
        Invoke-Core -Cleanup
    }
    $script:ownsCore = $false
    Save-State
}

function Test-Http([string]$url) {
    try { return (Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3).StatusCode -eq 200 }
    catch { return $false }
}

function Wait-Http([string]$url, $entry) {
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        if ($null -eq (Get-OwnedProcess $entry)) { throw "$($entry.Name) exited; see $runtime logs." }
        if (Test-Http $url) { return }
        Start-Sleep -Seconds 1
    }
    throw "Readiness timed out: $url. See $runtime logs."
}

function Start-Application([string]$name, [string]$executable, [string[]]$arguments, [string]$directory) {
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $directory `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "$name.stdout.log") `
        -RedirectStandardError (Join-Path $runtime "$name.stderr.log")
    $entry = @{ Name = $name; Id = $process.Id; StartTicks = $process.StartTime.ToUniversalTime().Ticks }
    $script:managed += $entry
    Save-State
    return $entry
}

function Run-Build([string]$directory, [string]$command, [string[]]$arguments, [string]$logName) {
    Push-Location $directory
    try {
        # Windows PowerShell treats redirected native stderr as ErrorRecords.
        $ErrorActionPreference = 'Continue'
        & $command @arguments *> (Join-Path $runtime $logName)
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) {
            Get-Content -LiteralPath (Join-Path $runtime $logName) -Tail 25
            throw "Build failed. See $runtime\$logName"
        }
    } finally { Pop-Location }
}

function Test-Docker {
    $probe = Start-Process -FilePath (Get-Command docker.exe).Source -ArgumentList @('ps', '--format', '{{.ID}}') `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'docker.log') `
        -RedirectStandardError (Join-Path $runtime 'docker.stderr.log')
    $null = $probe.Handle
    if (-not $probe.WaitForExit(10000)) { $probe.Kill(); return $false }
    $probe.WaitForExit()
    return $probe.ExitCode -eq 0
}

try {
    if (Test-Path -LiteralPath $stateFile) {
        $saved = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $managed = @($saved.Services)
        $ownsCore = [bool]$saved.OwnsCore
    }
    if ($Stop) {
        Stop-Applications
        Write-Host 'Project applications stopped. Database and Docker data are retained.'
        exit 0
    }
    $ready = $ownsCore -and $managed.Count -eq 2
    foreach ($entry in $managed) { if ($null -eq (Get-OwnedProcess $entry)) { $ready = $false } }
    if ($ready -and -not $Restart) {
        foreach ($url in @("$consoleUrl/agent-api/health", "$consoleUrl/actuator/health", "$consoleUrl/", 'http://127.0.0.1:18080/products?pageNo=1&pageSize=1', 'http://127.0.0.1:18082/healthz', 'http://127.0.0.1:6333/healthz')) {
            if (-not (Test-Http $url)) { $ready = $false }
        }
        if ($ready) {
            Write-Host "Already running: $consoleUrl"
            if (-not $NoBrowser) { Start-Process $consoleUrl }
            exit 0
        }
    }
    Stop-Applications
    Write-Host '[1/6] Loading local configuration and checking tools...'
    $configPath = Join-Path $repo '.env.local'
    if (-not (Test-Path -LiteralPath $configPath)) { throw 'Missing .env.local. See docs/local-start.md.' }
    foreach ($line in Get-Content -LiteralPath $configPath) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), 'Process')
        }
    }
    # This local stack calls loopback and the configured domestic model endpoints
    # directly. Do not inherit a desktop SOCKS proxy into httpx or npm.
    foreach ($proxyName in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')) {
        [Environment]::SetEnvironmentVariable($proxyName, $null, 'Process')
    }
    $env:NO_PROXY = 'localhost,127.0.0.1,::1'
    foreach ($name in @('APIOPS_STAGE21_DB_PASSWORD', 'ZHIPU_API_KEY', 'QWEN_API_KEY', 'QWEN_BASE_URL', 'QWEN_MODEL', 'STAGE21_NORMAL_PASSWORD', 'STAGE21_SAFETY41_PASSWORD', 'STAGE21_SAFETY42_PASSWORD')) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) { throw "Missing local setting: $name" }
    }
    # Spring AI's OpenAI adapter also supports Qwen's compatible endpoint.
    # Its default completion path already contains /v1; split the Python base URL.
    $env:APIOPS_STAGE21_JAVA_CHAT_MODEL = 'openai'
    $env:SPRING_AI_OPENAI_API_KEY = $env:QWEN_API_KEY
    $env:SPRING_AI_OPENAI_BASE_URL = $env:QWEN_BASE_URL.TrimEnd('/') -replace '/v1$', ''
    $env:SPRING_AI_OPENAI_CHAT_COMPLETIONS_PATH = '/v1/chat/completions'
    $env:SPRING_AI_OPENAI_CHAT_OPTIONS_MODEL = $env:QWEN_MODEL
    foreach ($tool in @('java.exe', 'node.exe', 'npm.cmd', 'python.exe', 'docker.exe', 'mysql.exe')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing required tool on PATH: $tool" }
    }
    $env:MYSQL_PWD = $env:APIOPS_STAGE21_DB_PASSWORD
    try {
        $databases = @(& mysql.exe -h 127.0.0.1 -u root -N -e "SHOW DATABASES LIKE 'apiops%';" 2>$null)
        if ($LASTEXITCODE -ne 0) { throw 'Cannot connect to local MySQL. Start the MySQL84 service and check .env.local.' }
        foreach ($db in @('apiops_auth', 'apiops_openapi', 'apiops_runner', 'apiops_rag', 'apiops_demo_order')) {
            if ($db -notin $databases) { throw "Missing database $db. See the initialization instructions in docs/local-start.md." }
        }
    } finally { Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue }
    if (-not (Test-Docker)) {
        $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (-not (Test-Path $desktop)) { throw 'Docker Desktop is not installed.' }
        Start-Process -FilePath $desktop -WindowStyle Hidden
        $deadline = (Get-Date).AddSeconds(180)
        do {
            Start-Sleep -Seconds 3
            $dockerReady = Test-Docker
            if ($dockerReady) { break }
        } while ((Get-Date) -lt $deadline)
        if (-not $dockerReady) { throw 'Docker Desktop did not become ready. See .local-run/docker.log.' }
    }
    # Use the existing identity-checked cleanup for a previous Stage21 session.
    if (Test-Path -LiteralPath $coreState) {
        Invoke-Core -Cleanup
    }
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object LocalPort -in 5173,18000,19090,8080,18080,18081,18082)
    if ($listeners.Count -gt 0) { throw "Required ports are occupied: $(($listeners.LocalPort | Sort-Object -Unique) -join ', '). No unrelated processes were stopped." }

    Write-Host '[2/6] Building Java and frontend (logs in .local-run)...'
    $javaRoot = Join-Path $repo 'java-apiops-platform'
    Run-Build $javaRoot (Join-Path $javaRoot 'mvnw.cmd') @('-B', '-DskipTests', 'package') 'java-build.log'
    $frontend = Join-Path $repo 'apiops-console'
    $npmStamp = Join-Path $runtime 'npm-dependencies.sha256'
    $npmHash = (Get-FileHash (Join-Path $frontend 'package-lock.json')).Hash
    if (-not (Test-Path (Join-Path $frontend 'node_modules/vite/bin/vite.js')) -or -not (Test-Path $npmStamp) -or (Get-Content $npmStamp -Raw).Trim() -ne $npmHash) {
        Run-Build $frontend 'npm.cmd' @('ci', '--no-audit', '--no-fund') 'npm-install.log'
        Set-Content $npmStamp $npmHash
    }
    Run-Build $frontend 'npm.cmd' @('run', 'build') 'frontend-build.log'
    $pythonRoot = Join-Path $repo 'python-apiops-agentlab'
    $python = Join-Path $pythonRoot '.venv\Scripts\python.exe'
    $createdPythonEnvironment = -not (Test-Path $python)
    if ($createdPythonEnvironment) { Run-Build $pythonRoot 'python.exe' @('-m', 'venv', '.venv') 'python-venv.log' }
    $pythonStamp = Join-Path $runtime 'python-dependencies.sha256'
    $pythonHash = (Get-FileHash (Join-Path $pythonRoot 'pyproject.toml')).Hash
    if ($createdPythonEnvironment -or -not (Test-Path $pythonStamp) -or (Get-Content $pythonStamp -Raw).Trim() -ne $pythonHash) {
        Run-Build $pythonRoot $python @('-m', 'ensurepip', '--upgrade') 'python-pip.log'
        Run-Build $pythonRoot $python @('-m', 'pip', 'install', '-e', '.') 'python-install.log'
        Set-Content $pythonStamp $pythonHash
    }

    Write-Host '[3/6] Starting infrastructure, Java backend and demo targets...'
    $ownsCore = $true
    Save-State
    Invoke-Core

    Write-Host '[4/6] Verifying all three test accounts...'
    foreach ($profile in @('NORMAL', 'SAFETY41', 'SAFETY42')) {
        $body = @{ username = [Environment]::GetEnvironmentVariable("STAGE21_${profile}_USERNAME"); password = [Environment]::GetEnvironmentVariable("STAGE21_${profile}_PASSWORD") } | ConvertTo-Json
        $login = Invoke-RestMethod -Uri 'http://127.0.0.1:19090/api/v1/auth/login' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 15
        if (-not $login.success -or -not $login.data.accessToken) { throw "Login failed: $profile" }
    }

    Write-Host '[5/6] Starting Python Agent and console...'
    $pythonEntry = Start-Application 'python' $python @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '18000') $pythonRoot
    Wait-Http 'http://127.0.0.1:18000/health' $pythonEntry
    $env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:19090'
    $env:VITE_PYTHON_API_PROXY_TARGET = 'http://127.0.0.1:18000'
    $node = (Get-Command node.exe).Source
    $frontEntry = Start-Application 'console' $node @('node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5173', '--strictPort') $frontend
    Wait-Http "$consoleUrl/" $frontEntry
    foreach ($url in @("$consoleUrl/actuator/health", "$consoleUrl/agent-api/health")) {
        if (-not (Test-Http $url)) { throw "Console proxy check failed: $url" }
    }
    $principal = Invoke-RestMethod -Uri "$consoleUrl/api/v1/auth/me" -Headers @{ Authorization = "Bearer $($login.data.accessToken)" } -TimeoutSec 10
    if (-not $principal.success) { throw 'Authenticated Java proxy check failed.' }
    # The final login above is SAFETY42, which cannot read project 41. A registered
    # controller must reject it before model invocation; a disabled controller is 404.
    # Use a nonexistent API as an additional guard against making a model call.
    $generationRouteStatus = 0
    try {
        $probe = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$consoleUrl/api/v1/projects/41/openapi/apis/__startup_route_probe__/testcases:generate" -ContentType 'application/json' -Body '{}' -Headers @{ Authorization = "Bearer $($login.data.accessToken)" } -TimeoutSec 10
        $generationRouteStatus = [int]$probe.StatusCode
    } catch {
        if ($null -ne $_.Exception.Response) { $generationRouteStatus = [int]$_.Exception.Response.StatusCode }
    }
    if ($generationRouteStatus -ne 403) { throw "Java generation route/isolation check failed (HTTP $generationRouteStatus)." }
    Write-Host "[6/6] READY: $consoleUrl"
    Write-Host 'Login: stage21-normal (password is in your supplied account list).'
    Write-Host 'To stop applications, double-click stop-project.cmd. To rebuild, run start-project.cmd -Restart.'
    if (-not $NoBrowser) { Start-Process $consoleUrl }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    try { Stop-Applications } catch { Write-Host "Cleanup: $($_.Exception.Message)" }
    exit 1
} finally { $lock.Dispose() }
