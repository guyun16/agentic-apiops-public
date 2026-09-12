[CmdletBinding()]
param(
    [switch]$Cleanup
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot 'stage21_start_live_services.ps1'
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'agentic-apiops-stage21-live'
$statePath = Join-Path $runtimeRoot 'current-runtime-state.json'
$runId = 'stage21-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$startedAt = [DateTime]::UtcNow.ToString('o')
$services = @()
$java = $null
$dockerPath = $null
$skipHttpErrorCheck = $false
$logRoot = $null

function Get-ProcessSnapshot {
    param([int]$ProcessId)

    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    } catch {
        return $null
    }
}

function Get-ProcessStartTimeUtc {
    param([int]$ProcessId)

    try {
        return (Get-Process -Id $ProcessId -ErrorAction Stop).StartTime.ToUniversalTime().ToString('o')
    } catch {
        return $null
    }
}

function Get-ProcessStartTimeUtcTicks {
    param([int]$ProcessId)

    try {
        return [int64]((Get-Process -Id $ProcessId -ErrorAction Stop).StartTime.ToUniversalTime().Ticks)
    } catch {
        return $null
    }
}

function Test-RecordedProcessStartTime {
    param([object]$Service)

    $currentTicks = Get-ProcessStartTimeUtcTicks -ProcessId ([int]$Service.ProcessId)
    if ($null -eq $currentTicks) {
        return $false
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Service.ProcessStartTimeUtcTicks)) {
        $expectedTicks = [int64]$Service.ProcessStartTimeUtcTicks
        return [Math]::Abs($currentTicks - $expectedTicks) -le [TimeSpan]::FromSeconds(2).Ticks
    }
    return $false
}

function Get-ProcessOwnerName {
    param([object]$ProcessInfo)

    if ($null -eq $ProcessInfo) {
        return 'unknown'
    }
    try {
        $owner = Invoke-CimMethod -InputObject $ProcessInfo -MethodName GetOwner -ErrorAction Stop
        if ($owner.ReturnValue -eq 0 -and -not [string]::IsNullOrWhiteSpace($owner.User)) {
            if ([string]::IsNullOrWhiteSpace($owner.Domain)) {
                return [string]$owner.User
            }
            return "$($owner.Domain)\$($owner.User)"
        }
    } catch {
        # Process owner is diagnostic only; inability to read it must not change cleanup scope.
    }
    return 'unknown'
}

function Get-ListeningPortOwners {
    param([int]$Port)

    $connections = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    $owners = @()
    foreach ($connection in $connections) {
        $processInfo = Get-ProcessSnapshot -ProcessId ([int]$connection.OwningProcess)
        $owners += [pscustomobject]@{
            ProcessId = [int]$connection.OwningProcess
            ProcessName = if ($null -ne $processInfo) { [string]$processInfo.Name } else { 'unknown' }
            ProcessOwner = Get-ProcessOwnerName -ProcessInfo $processInfo
            CommandLine = if ($null -ne $processInfo) { [string]$processInfo.CommandLine } else { '' }
        }
    }
    return @($owners)
}

function Format-PortOwners {
    param([object[]]$Owners)

    $descriptions = @(
        $Owners | ForEach-Object {
            "PID=$($_.ProcessId) owner=$($_.ProcessOwner) process=$($_.ProcessName) command=$($_.CommandLine)"
        }
    )
    return ($descriptions -join '; ')
}

function Assert-Stage21PortsFree {
    param([int[]]$Ports)

    foreach ($port in ($Ports | Sort-Object -Unique)) {
        $owners = @(Get-ListeningPortOwners -Port $port)
        if ($owners.Count -gt 0) {
            throw "required Stage21 port $port is already occupied: $(Format-PortOwners -Owners $owners)"
        }
    }
}

function Assert-ManagedProcess {
    param([object]$Service)

    $processInfo = Get-ProcessSnapshot -ProcessId ([int]$Service.ProcessId)
    if ($null -eq $processInfo) {
        throw "$($Service.Name) PID $($Service.ProcessId) exited before readiness; see $($Service.Stdout) and $($Service.Stderr)"
    }

    $commandLine = [string]$processInfo.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine) -or
        $commandLine.IndexOf([string]$Service.IdentityToken, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "$($Service.Name) PID $($Service.ProcessId) no longer matches its recorded identity; current command=$commandLine"
    }

    if (-not (Test-RecordedProcessStartTime -Service $Service)) {
        throw "$($Service.Name) PID $($Service.ProcessId) was replaced by a process with a different or unverifiable start time"
    }
    return $processInfo
}

function Stop-ManagedProcess {
    param([object]$Service)

    $processInfo = Get-ProcessSnapshot -ProcessId ([int]$Service.ProcessId)
    if ($null -eq $processInfo) {
        return
    }

    $commandLine = [string]$processInfo.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine) -or
        $commandLine.IndexOf([string]$Service.IdentityToken, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Write-Warning "Skipping cleanup for PID $($Service.ProcessId): command identity does not match $($Service.IdentityToken)"
        return
    }

    if (-not (Test-RecordedProcessStartTime -Service $Service)) {
        Write-Warning "Skipping cleanup for PID $($Service.ProcessId): process start time does not match recorded Stage21 process"
        return
    }

    Stop-Process -Id ([int]$Service.ProcessId) -ErrorAction SilentlyContinue
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ($null -eq (Get-Process -Id ([int]$Service.ProcessId) -ErrorAction SilentlyContinue)) {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    if ($null -ne (Get-Process -Id ([int]$Service.ProcessId) -ErrorAction SilentlyContinue)) {
        Stop-Process -Id ([int]$Service.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ManagedServices {
    for ($index = $services.Count - 1; $index -ge 0; $index--) {
        Stop-ManagedProcess -Service $services[$index]
    }
}

function Write-Stage21State {
    param([string]$Status)

    if (-not (Test-Path -LiteralPath $runtimeRoot)) {
        New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    }
    $state = [pscustomobject]@{
        SchemaVersion = 'stage21-runtime-world/v2'
        Status = $Status
        RunId = $runId
        StartedAt = $startedAt
        UpdatedAt = [DateTime]::UtcNow.ToString('o')
        Script = $scriptPath
        CleanupCommand = "powershell.exe -ExecutionPolicy Bypass -File `"$scriptPath`" -Cleanup"
        ModelCalls = 0
        Services = @($services | ForEach-Object {
                [pscustomobject]@{
                    Name = $_.Name
                    Owner = $_.Owner
                    Module = $_.Module
                    Port = $_.Port
                    ProcessId = $_.ProcessId
                    Executable = $_.Executable
                    IdentityToken = $_.IdentityToken
                    ProcessStartTimeUtc = $_.ProcessStartTimeUtc
                    ProcessStartTimeUtcTicks = $_.ProcessStartTimeUtcTicks
                    Stdout = $_.Stdout
                    Stderr = $_.Stderr
                    ReadinessUri = $_.ReadinessUri
                    ReadinessKind = $_.ReadinessKind
                    Readiness = $_.Readiness
                    Behavior = $_.Behavior
                }
            })
    }
    $state | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$Owner,
        [string]$Module,
        [int]$Port,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$IdentityToken,
        [string]$ReadinessUri,
        [string]$ReadinessKind
    )

    $stdout = Join-Path $logRoot "$Name.stdout.log"
    $stderr = Join-Path $logRoot "$Name.stderr.log"
    $process = Start-Process -FilePath $FilePath -WindowStyle Hidden -WorkingDirectory $repo `
        -ArgumentList $Arguments -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

    $startTimeUtc = $null
    $startTimeUtcTicks = $null
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $startTimeUtc = Get-ProcessStartTimeUtc -ProcessId $process.Id
        $startTimeUtcTicks = Get-ProcessStartTimeUtcTicks -ProcessId $process.Id
        if ($null -ne $startTimeUtc -and $null -ne $startTimeUtcTicks) {
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($null -eq $startTimeUtc -or $null -eq $startTimeUtcTicks) {
        throw "$Name started without a readable process start time; see $stdout and $stderr"
    }

    return [pscustomobject]@{
        Name = $Name
        Owner = $Owner
        Module = $Module
        Port = $Port
        ProcessId = [int]$process.Id
        Executable = $FilePath
        IdentityToken = $IdentityToken
        ProcessStartTimeUtc = $startTimeUtc
        ProcessStartTimeUtcTicks = $startTimeUtcTicks
        Stdout = $stdout
        Stderr = $stderr
        ReadinessUri = $ReadinessUri
        ReadinessKind = $ReadinessKind
        Readiness = $null
        Behavior = $null
    }
}

function Invoke-Compose {
    param(
        [string]$ComposeFile,
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    & $dockerPath compose -f $ComposeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Get-ComposePublishedPort {
    param(
        [string]$ContainerId,
        [int]$ContainerPort
    )

    $mappings = @(& $dockerPath port $ContainerId "$ContainerPort/tcp" 2>$null)
    foreach ($mapping in $mappings) {
        if ([string]$mapping -match ':(\d+)$') {
            return [int]$Matches[1]
        }
    }
    throw "Docker container $ContainerId does not publish host port for $ContainerPort/tcp"
}

function Wait-ComposeHealthy {
    param(
        [string]$ComposeFile,
        [string]$Service,
        [int]$ContainerPort,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = 'not-found'
    while ((Get-Date) -lt $deadline) {
        $containerId = [string](& $dockerPath compose -f $ComposeFile ps -q $Service 2>$null | Select-Object -First 1)
        $containerId = $containerId.Trim()
        if (-not [string]::IsNullOrWhiteSpace($containerId)) {
            $lastState = [string](& $dockerPath inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' $containerId 2>$null)
            $lastState = $lastState.Trim()
            if ($lastState -eq 'running|healthy') {
                $hostPort = Get-ComposePublishedPort -ContainerId $containerId -ContainerPort $ContainerPort
                return [pscustomobject]@{
                    Service = $Service
                    ContainerId = $containerId
                    Status = 'READY'
                    State = $lastState
                    Host = '127.0.0.1'
                    HostPort = $hostPort
                }
            }
        }
        Start-Sleep -Milliseconds 1000
    }
    throw "$Service compose readiness failed after ${TimeoutSeconds}s; last state=$lastState"
}

function Wait-LocalTcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = 'connection was not established'
    while ((Get-Date) -lt $deadline) {
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $connect = $client.ConnectAsync($HostName, $Port)
            if ($connect.Wait(1000) -and $client.Connected) {
                return [pscustomobject]@{
                    Service = 'mysql'
                    ContainerId = $null
                    Status = 'READY'
                    State = 'local-tcp'
                    Host = $HostName
                    HostPort = $Port
                }
            }
            $lastError = "TCP connection to ${HostName}:$Port was not established"
        } catch {
            $lastError = $_.Exception.Message
        } finally {
            $client.Dispose()
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Local MySQL readiness failed after ${TimeoutSeconds}s for ${HostName}:$Port; last error=$lastError"
}

function Invoke-RuntimeRequest {
    param(
        [string]$Uri,
        [string]$Method = 'GET',
        [string]$Body = $null,
        [string]$ContentType = 'application/json',
        [int]$TimeoutSeconds = 3
    )

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $statusCode = 0
    $content = ''
    $transportFailure = $false
    $errorMessage = $null
    $parameters = @{
        Uri = $Uri
        Method = $Method
        UseBasicParsing = $true
        TimeoutSec = $TimeoutSeconds
    }
    if (-not [string]::IsNullOrEmpty($Body)) {
        $parameters.Body = $Body
        $parameters.ContentType = $ContentType
    }
    if ($skipHttpErrorCheck) {
        $parameters.SkipHttpErrorCheck = $true
    }

    try {
        $response = Invoke-WebRequest @parameters
        $statusCode = [int]$response.StatusCode
        $content = [string]$response.Content
    } catch {
        $webResponse = $_.Exception.Response
        if ($null -ne $webResponse) {
            $statusCode = [int]$webResponse.StatusCode
            try {
                $reader = New-Object System.IO.StreamReader($webResponse.GetResponseStream())
                try {
                    $content = $reader.ReadToEnd()
                } finally {
                    $reader.Dispose()
                }
            } catch {
                $content = ''
            }
        } else {
            $transportFailure = $true
            $errorMessage = $_.Exception.Message
        }
    } finally {
        $stopwatch.Stop()
    }

    return [pscustomobject]@{
        Uri = $Uri
        StatusCode = $statusCode
        Content = $content
        ElapsedMs = [Math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
        TransportFailure = $transportFailure
        Error = $errorMessage
    }
}

function Get-JsonBody {
    param([object]$Response)

    if ($null -eq $Response -or [string]::IsNullOrWhiteSpace([string]$Response.Content)) {
        return $null
    }
    try {
        return ([string]$Response.Content | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Test-ProductResponse {
    param([object]$Response)

    $body = Get-JsonBody -Response $Response
    $contentReportsProductPage = ([string]$Response.Content) -match '"success"\s*:\s*true' -and
        ([string]$Response.Content) -match '"code"\s*:\s*"ORDER_SUCCESS"' -and
        ([string]$Response.Content) -match '"records"\s*:'
    return $Response.StatusCode -eq 200 -and
        $Response.TransportFailure -eq $false -and
        (($null -ne $body -and
            $body.success -eq $true -and
            $body.code -eq 'ORDER_SUCCESS' -and
            $null -ne $body.data -and
            @($body.data.records).Count -gt 0) -or $contentReportsProductPage)
}

function Test-FaultResponse {
    param([object]$Response)

    $body = Get-JsonBody -Response $Response
    $contentReportsFault = ([string]$Response.Content) -match '"success"\s*:\s*false' -and
        ([string]$Response.Content) -match '"code"\s*:\s*"ORDER_SYSTEM_ERROR"'
    return $Response.StatusCode -eq 500 -and
        $Response.TransportFailure -eq $false -and
        (($null -ne $body -and
            $body.success -eq $false -and
            $body.code -eq 'ORDER_SYSTEM_ERROR') -or $contentReportsFault)
}

function Test-ApiOpsWebHealth {
    param([object]$Response)

    $body = Get-JsonBody -Response $Response
    # /actuator/health uses the HTTP status code as its readiness contract.
    # Keep the body check when available, but do not depend on a PowerShell
    # response-body representation for an otherwise healthy actuator response.
    return $Response.StatusCode -eq 200 -and
        $Response.TransportFailure -eq $false -and
        ($null -eq $body -or $body.status -eq 'UP' -or
            ([string]$Response.Content) -match '"status"\s*:\s*"UP"')
}

function Test-TimeoutTargetHealth {
    param([object]$Response)

    $body = Get-JsonBody -Response $Response
    $contentReportsReady = ([string]$Response.Content) -match '"service"\s*:\s*"stage21-timeout-target"' -and
        ([string]$Response.Content) -match '"status"\s*:\s*"READY"'
    return $Response.StatusCode -eq 200 -and
        $Response.TransportFailure -eq $false -and
        (($null -ne $body -and
            $body.service -eq 'stage21-timeout-target' -and
            $body.status -eq 'READY') -or $contentReportsReady)
}

function Test-ServiceReadiness {
    param(
        [object]$Service,
        [object]$Response
    )

    switch ($Service.ReadinessKind) {
        'APIOPS_WEB_HEALTH' { return Test-ApiOpsWebHealth -Response $Response }
        'PRODUCT_PAGE' { return Test-ProductResponse -Response $Response }
        'CONTROLLED_HTTP500' { return Test-FaultResponse -Response $Response }
        'TIMEOUT_TARGET_HEALTH' { return Test-TimeoutTargetHealth -Response $Response }
        default { throw "unknown readiness kind $($Service.ReadinessKind) for $($Service.Name)" }
    }
}

function Get-ResponseCode {
    param([object]$Response)

    $body = Get-JsonBody -Response $Response
    if ($null -eq $body) {
        if ([string]$Response.Content -match '"code"\s*:\s*"([^"]+)"') {
            return [string]$Matches[1]
        }
        return $null
    }
    return [string]$body.code
}

function Wait-ServiceReadiness {
    param(
        [object]$Service,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastResponse = $null
    while ((Get-Date) -lt $deadline) {
        Assert-ManagedProcess -Service $Service | Out-Null
        $lastResponse = Invoke-RuntimeRequest -Uri $Service.ReadinessUri -TimeoutSeconds 3
        if (Test-ServiceReadiness -Service $Service -Response $lastResponse) {
            $Service.Readiness = [pscustomobject]@{
                Status = 'READY'
                Uri = $Service.ReadinessUri
                HttpStatus = $lastResponse.StatusCode
                SemanticCode = Get-ResponseCode -Response $lastResponse
                ElapsedMs = $lastResponse.ElapsedMs
                TransportFailure = $lastResponse.TransportFailure
            }
            return
        }
        Start-Sleep -Milliseconds 500
    }

    $lastStatus = if ($null -ne $lastResponse) { $lastResponse.StatusCode } else { 0 }
    $lastError = if ($null -ne $lastResponse) { $lastResponse.Error } else { 'no response' }
    throw "$($Service.Name) readiness failed after ${TimeoutSeconds}s; uri=$($Service.ReadinessUri) status=$lastStatus error=$lastError; see $($Service.Stdout) and $($Service.Stderr)"
}

function Assert-Response {
    param(
        [object]$Response,
        [scriptblock]$Predicate,
        [string]$FailureMessage
    )

    if (-not (& $Predicate $Response)) {
        $bodyPreview = ([string]$Response.Content).Trim()
        if ($bodyPreview.Length -gt 240) {
            $bodyPreview = $bodyPreview.Substring(0, 240)
        }
        throw "$FailureMessage; status=$($Response.StatusCode) transportFailure=$($Response.TransportFailure) elapsedMs=$($Response.ElapsedMs) body=$bodyPreview error=$($Response.Error)"
    }
}

if ($Cleanup) {
    if (-not (Test-Path -LiteralPath $statePath)) {
        [pscustomobject]@{
            Status = 'NO_RUNTIME_STATE'
            StatePath = $statePath
            StoppedProcessCount = 0
        } | ConvertTo-Json -Depth 4
        exit 0
    }

    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $services = @($state.Services)
    $stopped = 0
    $remaining = @()
    for ($index = $services.Count - 1; $index -ge 0; $index--) {
        $before = Get-ProcessSnapshot -ProcessId ([int]$services[$index].ProcessId)
        Stop-ManagedProcess -Service $services[$index]
        $after = Get-ProcessSnapshot -ProcessId ([int]$services[$index].ProcessId)
        if ($null -ne $before -and $null -eq $after) {
            $stopped++
        } elseif ($null -ne $after) {
            $remaining += [int]$services[$index].ProcessId
        }
    }
    if ($remaining.Count -gt 0) {
        [pscustomobject]@{
            Status = 'CLEANUP_INCOMPLETE'
            RunId = $state.RunId
            StatePath = $statePath
            StoppedProcessCount = $stopped
            RemainingProcessIds = @($remaining)
            Scope = 'recorded Stage21 child processes only; state retained for a safe retry'
        } | ConvertTo-Json -Depth 4
        exit 1
    }
    if (Test-Path -LiteralPath $statePath) {
        Remove-Item -LiteralPath $statePath -Force
    }
    [pscustomobject]@{
        Status = 'CLEANED'
        RunId = $state.RunId
        StatePath = $statePath
        StoppedProcessCount = $stopped
        Scope = 'recorded Stage21 child processes only; Docker dependencies were not stopped'
    } | ConvertTo-Json -Depth 4
    exit 0
}

$startupSucceeded = $false
$failureMessage = $null
try {
    if (Test-Path -LiteralPath $statePath) {
        throw "a Stage21 runtime state already exists at $statePath; run this script with -Cleanup before starting another runtime world"
    }

    $embeddingApiKey = [Environment]::GetEnvironmentVariable('ZHIPU_API_KEY', 'Process')
    if ([string]::IsNullOrWhiteSpace($embeddingApiKey)) {
        throw 'ZHIPU_API_KEY must be provided through the Stage21 runtime environment before apiops-web startup'
    }
    $env:ZHIPU_API_KEY = $embeddingApiKey.Trim()

    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $logRoot = Join-Path $runtimeRoot "run-$runId"
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

    if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME)) {
        $java = Join-Path $env:JAVA_HOME 'bin\java.exe'
        if (-not (Test-Path -LiteralPath $java)) {
            throw "JAVA_HOME does not contain a Java executable: $java"
        }
    } else {
        $javaCommand = @(Get-Command java -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($javaCommand.Count -eq 0) {
            throw 'Java is not available; set JAVA_HOME or put java on PATH'
        }
        $java = [string]$javaCommand[0].Path
    }

    $dockerCommand = @(Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($dockerCommand.Count -eq 0) {
        throw 'Docker is not available; Stage21 core dependencies and Qdrant are required'
    }
    $dockerPath = [string]$dockerCommand[0].Path

    $pythonCommand = @(Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1)
    $pythonArgumentsPrefix = @()
    if ($pythonCommand.Count -eq 0) {
        $pythonCommand = @(Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($pythonCommand.Count -eq 0) {
            throw 'Python is not available; the standalone Stage21 timeout target cannot start'
        }
        $pythonArgumentsPrefix = @('-3')
    }

    $coreComposeFile = Join-Path $repo 'docker-compose.dev.yml'
    $qdrantComposeFile = Join-Path $repo 'java-apiops-platform\docker-compose.rag.yml'
    $webJar = Join-Path $repo 'java-apiops-platform\apiops-web\target\apiops-web-0.1.0-SNAPSHOT.jar'
    $orderJar = Join-Path $repo 'java-apiops-platform\apiops-demo-order-service\target\apiops-demo-order-service-0.1.0-SNAPSHOT.jar'
    $timeoutScript = Join-Path $repo 'python-apiops-agentlab\scripts\stage21_timeout_target.py'
    $toolGatewaySchemaScript = Join-Path $repo 'scripts\apply-tool-gateway-schema.ps1'
    $runnerSchemaScript = Join-Path $repo 'scripts\apply-runner-schema.ps1'
    $qdrantBaseUrl = $env:APIOPS_RAG_QDRANT_BASE_URL
    if ([string]::IsNullOrWhiteSpace($qdrantBaseUrl)) {
        $qdrantBaseUrl = 'http://127.0.0.1:6333'
    }
    $qdrantBaseUrl = $qdrantBaseUrl.TrimEnd('/')
    $dbPassword = $env:APIOPS_STAGE21_DB_PASSWORD
    if ([string]::IsNullOrWhiteSpace($dbPassword)) {
        throw 'APIOPS_STAGE21_DB_PASSWORD must be provided through the Stage21 runtime environment'
    }
    $mysqlSource = [string]$env:APIOPS_STAGE21_MYSQL_SOURCE
    if ([string]::IsNullOrWhiteSpace($mysqlSource)) {
        $mysqlSource = 'local'
    }
    $mysqlSource = $mysqlSource.Trim().ToLowerInvariant()
    if ($mysqlSource -notin @('local', 'docker')) {
        throw "APIOPS_STAGE21_MYSQL_SOURCE must be 'local' or 'docker'; received '$mysqlSource'"
    }

    $pythonPath = [string]$pythonCommand[0].Path
    foreach ($path in @($java, $dockerPath, $pythonPath, $coreComposeFile, $qdrantComposeFile, $webJar, $orderJar, $timeoutScript, $toolGatewaySchemaScript)) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "required runtime file is missing: $path"
        }
    }

    $invokeWebRequestCommand = Get-Command Invoke-WebRequest -ErrorAction Stop
    $skipHttpErrorCheck = $invokeWebRequestCommand.Parameters.ContainsKey('SkipHttpErrorCheck')

    Assert-Stage21PortsFree -Ports @(18080, 18081, 18082, 8080, 19090)

    $composePortVariables = @(
        'APIOPS_DEV_REDIS_PORT',
        'APIOPS_DEV_RABBITMQ_PORT',
        'APIOPS_DEV_RABBITMQ_MANAGEMENT_PORT'
    )
    if ($mysqlSource -eq 'docker') {
        $composePortVariables += 'APIOPS_DEV_MYSQL_PORT'
    }
    $previousComposePorts = @{}
    try {
        foreach ($variable in $composePortVariables) {
            $previousComposePorts[$variable] = [Environment]::GetEnvironmentVariable($variable, 'Process')
            if ([string]::IsNullOrWhiteSpace($previousComposePorts[$variable])) {
                [Environment]::SetEnvironmentVariable($variable, '0', 'Process')
            }
        }

        $coreServices = @('redis', 'rabbitmq')
        if ($mysqlSource -eq 'docker') {
            $coreServices = @('mysql', 'redis', 'rabbitmq')
        }
        Invoke-Compose -ComposeFile $coreComposeFile -Arguments (@('up', '-d') + $coreServices) `
            -FailureMessage 'Stage21 core dependency startup failed (Redis/RabbitMQ)'
        if ($mysqlSource -eq 'docker') {
            $mysqlReady = Wait-ComposeHealthy -ComposeFile $coreComposeFile -Service 'mysql' -ContainerPort 3306
        } else {
            $mysqlReady = Wait-LocalTcpPort -HostName '127.0.0.1' -Port 3306
        }
        & $toolGatewaySchemaScript -HostName $mysqlReady.Host -Port $mysqlReady.HostPort `
            -Username 'root' -Password $dbPassword
        & $runnerSchemaScript -HostName $mysqlReady.Host -Port $mysqlReady.HostPort `
            -Username 'root' -Password $dbPassword
        $redisReady = Wait-ComposeHealthy -ComposeFile $coreComposeFile -Service 'redis' -ContainerPort 6379
        $rabbitReady = Wait-ComposeHealthy -ComposeFile $coreComposeFile -Service 'rabbitmq' -ContainerPort 5672

        $redisFixtureKey = 'apiops:runner:progress:41:701'
        & $dockerPath exec $redisReady.ContainerId redis-cli HSET $redisFixtureKey `
            projectId 41 status READY | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Stage21 required Redis read fixture HSET failed'
        }
        & $dockerPath exec $redisReady.ContainerId redis-cli EXPIRE $redisFixtureKey 86400 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Stage21 required Redis read fixture expiration failed'
        }
        $redisFixtureValue = [string](& $dockerPath exec $redisReady.ContainerId `
                redis-cli HGET $redisFixtureKey status 2>$null)
        if ($LASTEXITCODE -ne 0 -or $redisFixtureValue.Trim() -ne 'READY') {
            throw 'Stage21 required Redis read fixture verification failed'
        }
        $redisFixture = [pscustomobject]@{
            Status = 'PASS'
            LogicalKey = 'runner:701'
            PhysicalKey = $redisFixtureKey
            Command = 'HGET'
            Field = 'status'
        }
    } finally {
        foreach ($variable in $composePortVariables) {
            [Environment]::SetEnvironmentVariable($variable, $previousComposePorts[$variable], 'Process')
        }
    }

    Invoke-Compose -ComposeFile $qdrantComposeFile -Arguments @('up', '-d', 'qdrant') `
        -FailureMessage 'Stage21 Qdrant startup failed'
    $qdrantResponse = $null
    $qdrantReady = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        $qdrantResponse = Invoke-RuntimeRequest -Uri "$qdrantBaseUrl/healthz" -TimeoutSeconds 2
        if ($qdrantResponse.StatusCode -eq 200 -and -not $qdrantResponse.TransportFailure) {
            $qdrantReady = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $qdrantReady) {
        throw "Qdrant readiness failed: $qdrantBaseUrl/healthz status=$($qdrantResponse.StatusCode) error=$($qdrantResponse.Error)"
    }

    $jwtSecret = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('stage21-local-jwt-secret-2026-08-28-acceptance'))
    $env:APIOPS_AUTH_DB_URL = "jdbc:mysql://$($mysqlReady.Host):$($mysqlReady.HostPort)/apiops_auth"
    $env:APIOPS_AUTH_DB_USERNAME = 'root'
    $env:APIOPS_AUTH_DB_PASSWORD = $dbPassword
    $env:APIOPS_OPENAPI_DB_URL = "jdbc:mysql://$($mysqlReady.Host):$($mysqlReady.HostPort)/apiops_openapi"
    $env:APIOPS_OPENAPI_DB_USERNAME = 'root'
    $env:APIOPS_OPENAPI_DB_PASSWORD = $dbPassword
    $env:APIOPS_RUNNER_DB_URL = "jdbc:mysql://$($mysqlReady.Host):$($mysqlReady.HostPort)/apiops_runner"
    $env:APIOPS_RUNNER_DB_USERNAME = 'root'
    $env:APIOPS_RUNNER_DB_PASSWORD = $dbPassword
    $env:APIOPS_TOOL_GATEWAY_DB_URL = "jdbc:mysql://$($mysqlReady.Host):$($mysqlReady.HostPort)/apiops_tool_gateway"
    $env:APIOPS_TOOL_GATEWAY_DB_USERNAME = 'root'
    $env:APIOPS_TOOL_GATEWAY_DB_PASSWORD = $dbPassword
    $env:APIOPS_RAG_DB_URL = "jdbc:mysql://$($mysqlReady.Host):$($mysqlReady.HostPort)/apiops_rag"
    $env:APIOPS_RAG_DB_USERNAME = 'root'
    $env:APIOPS_RAG_DB_PASSWORD = $dbPassword
    $env:APIOPS_RABBITMQ_HOST = '127.0.0.1'
    $env:APIOPS_RABBITMQ_PORT = [string]$rabbitReady.HostPort
    $env:APIOPS_RABBITMQ_USERNAME = 'guest'
    $env:APIOPS_RABBITMQ_PASSWORD = 'guest'
    $env:APIOPS_RABBITMQ_EXECUTION_ENABLED = 'true'
    $env:APIOPS_RABBITMQ_EXECUTION_EXCHANGE = 'apiops.stage21.live.exchange'
    $env:APIOPS_RABBITMQ_EXECUTION_ROUTING_KEY = 'apiops.stage21.live.run'
    $env:APIOPS_RABBITMQ_EXECUTION_QUEUE = 'apiops.stage21.live.queue'
    $env:APIOPS_RABBITMQ_EXECUTION_DLX = 'apiops.stage21.live.dlx'
    $env:APIOPS_RABBITMQ_EXECUTION_DLQ_ROUTING_KEY = 'apiops.stage21.live.dead'
    $env:APIOPS_RABBITMQ_EXECUTION_DLQ = 'apiops.stage21.live.dlq'
    $env:APIOPS_RUNNER_PROGRESS_ENABLED = 'true'
    $env:APIOPS_RUNNER_PROGRESS_TTL = '10m'
    $env:APIOPS_RUNNER_PROGRESS_SSE_TIMEOUT = '2m'
    $env:APIOPS_REDIS_HOST = '127.0.0.1'
    $env:APIOPS_REDIS_PORT = [string]$redisReady.HostPort
    $env:APIOPS_REDIS_PASSWORD = ''
    $env:APIOPS_REDIS_HEALTH_ENABLED = 'true'
    $env:APIOPS_RAG_QDRANT_ENABLED = 'true'
    $env:APIOPS_RAG_QDRANT_BASE_URL = $qdrantBaseUrl
    $env:APIOPS_JWT_SECRET = $jwtSecret

    # Benchmark callers retain the no-chat default; the interactive launcher opts in.
    $javaChatModel = [string]$env:APIOPS_STAGE21_JAVA_CHAT_MODEL
    if ([string]::IsNullOrWhiteSpace($javaChatModel)) { $javaChatModel = 'none' }
    if ($javaChatModel -notin @('none', 'openai')) {
        throw 'APIOPS_STAGE21_JAVA_CHAT_MODEL must be none or openai'
    }
    $services += Start-ManagedProcess -Name 'apiops-web-19090' -Owner 'apiops-web' `
        -Module 'java-apiops-platform/apiops-web' -Port 19090 -FilePath $java -IdentityToken 'apiops-web-0.1.0-SNAPSHOT.jar' `
        -Arguments @('-jar', $webJar, '--spring.profiles.active=local', '--server.address=127.0.0.1', '--server.port=19090', "--spring.ai.model.chat=$javaChatModel", '--spring.ai.model.embedding=none') `
        -ReadinessUri 'http://127.0.0.1:19090/actuator/health' -ReadinessKind 'APIOPS_WEB_HEALTH'
    Write-Stage21State -Status 'STARTING'

    $env:APIOPS_ORDER_DB_URL = "jdbc:mysql://$($mysqlReady.Host):$($mysqlReady.HostPort)/apiops_demo_order"
    $env:APIOPS_ORDER_DB_USERNAME = 'root'
    $env:APIOPS_ORDER_DB_PASSWORD = $dbPassword
    $services += Start-ManagedProcess -Name 'demo-order-18080' -Owner 'apiops-demo-order-service' `
        -Module 'java-apiops-platform/apiops-demo-order-service' -Port 18080 -FilePath $java -IdentityToken 'apiops-demo-order-service-0.1.0-SNAPSHOT.jar' `
        -Arguments @('-jar', $orderJar, '--spring.profiles.active=local', '--server.address=127.0.0.1', '--server.port=18080', '--apiops.fault.enabled=true') `
        -ReadinessUri 'http://127.0.0.1:18080/products?pageNo=1&pageSize=1' -ReadinessKind 'PRODUCT_PAGE'
    Write-Stage21State -Status 'STARTING'

    $services += Start-ManagedProcess -Name 'demo-order-8080' -Owner 'apiops-demo-order-service' `
        -Module 'java-apiops-platform/apiops-demo-order-service' -Port 8080 -FilePath $java -IdentityToken 'apiops-demo-order-service-0.1.0-SNAPSHOT.jar' `
        -Arguments @('-jar', $orderJar, '--spring.profiles.active=local', '--server.address=127.0.0.1', '--server.port=8080', '--apiops.fault.enabled=true') `
        -ReadinessUri 'http://127.0.0.1:8080/products?pageNo=1&pageSize=1' -ReadinessKind 'PRODUCT_PAGE'
    Write-Stage21State -Status 'STARTING'

    $env:APIOPS_ORDER_DB_URL = 'jdbc:mysql://127.0.0.1:1/apiops_demo_order'
    $services += Start-ManagedProcess -Name 'demo-order-18081-fault' -Owner 'apiops-demo-order-service' `
        -Module 'java-apiops-platform/apiops-demo-order-service' -Port 18081 -FilePath $java -IdentityToken 'apiops-demo-order-service-0.1.0-SNAPSHOT.jar' `
        -Arguments @('-jar', $orderJar, '--spring.profiles.active=local', '--server.address=127.0.0.1', '--server.port=18081', '--apiops.fault.enabled=true') `
        -ReadinessUri 'http://127.0.0.1:18081/api/faults/slow-sql?delayMs=100' -ReadinessKind 'CONTROLLED_HTTP500'
    Write-Stage21State -Status 'STARTING'

    $services += Start-ManagedProcess -Name 'stage21-timeout-target-18082' -Owner 'stage21-timeout-target' `
        -Module 'python-apiops-agentlab/scripts/stage21_timeout_target.py' -Port 18082 -FilePath $pythonPath `
        -IdentityToken 'stage21_timeout_target.py' -Arguments ($pythonArgumentsPrefix + @($timeoutScript)) `
        -ReadinessUri 'http://127.0.0.1:18082/healthz' -ReadinessKind 'TIMEOUT_TARGET_HEALTH'
    Write-Stage21State -Status 'STARTING'

    foreach ($service in $services) {
        Wait-ServiceReadiness -Service $service
        Write-Stage21State -Status 'STARTING'
    }

    $serviceByName = @{}
    foreach ($service in $services) {
        $serviceByName[$service.Name] = $service
    }

    $productsResponse = Invoke-RuntimeRequest -Uri 'http://127.0.0.1:18080/products?pageNo=1&pageSize=1' -TimeoutSeconds 5
    Assert-Response -Response $productsResponse -Predicate { param($response) Test-ProductResponse -Response $response } `
        -FailureMessage '18080 /products did not return a valid product page'
    $productsBody = Get-JsonBody -Response $productsResponse
    $serviceByName['demo-order-18080'].Behavior = [pscustomobject]@{
        Status = 'PASS'
        Method = 'GET'
        Path = '/products?pageNo=1&pageSize=1'
        HttpStatus = $productsResponse.StatusCode
        SemanticCode = [string]$productsBody.code
        RecordCount = @($productsBody.data.records).Count
        ElapsedMs = $productsResponse.ElapsedMs
        TransportFailure = $productsResponse.TransportFailure
    }

    $faultResponse = Invoke-RuntimeRequest -Uri 'http://127.0.0.1:18081/api/faults/slow-sql?delayMs=100' -TimeoutSeconds 5
    Assert-Response -Response $faultResponse -Predicate { param($response) Test-FaultResponse -Response $response } `
        -FailureMessage '18081 controlled slow-sql fault did not return a real HTTP 500 envelope'
    $faultBody = Get-JsonBody -Response $faultResponse
    $serviceByName['demo-order-18081-fault'].Behavior = [pscustomobject]@{
        Status = 'PASS'
        Method = 'GET'
        Path = '/api/faults/slow-sql?delayMs=100'
        HttpStatus = $faultResponse.StatusCode
        SemanticCode = [string]$faultBody.code
        ElapsedMs = $faultResponse.ElapsedMs
        TransportFailure = $faultResponse.TransportFailure
    }

    $timeoutResponse = Invoke-RuntimeRequest -Uri 'http://127.0.0.1:18082/timeout' -TimeoutSeconds 12
    Assert-Response -Response $timeoutResponse -Predicate {
        param($response)
        $response.StatusCode -eq 200 -and
            $response.TransportFailure -eq $false -and
            $response.ElapsedMs -ge 8000 -and
            ([string]$response.Content).Trim() -eq 'timeout target completed'
    } -FailureMessage '18082 /timeout did not demonstrate a genuine slow HTTP response'
    Assert-ManagedProcess -Service $serviceByName['stage21-timeout-target-18082'] | Out-Null
    $serviceByName['stage21-timeout-target-18082'].Behavior = [pscustomobject]@{
        Status = 'PASS'
        Method = 'GET'
        Path = '/timeout'
        HttpStatus = $timeoutResponse.StatusCode
        ActualDelayMs = $timeoutResponse.ElapsedMs
        TransportFailure = $timeoutResponse.TransportFailure
        RunnerTimeoutAuthority = 'JAVA_RUNNER'
    }

    $inventoryBody = @{ userId = 1; items = @(@{ productId = 2; quantity = 3 }) } | ConvertTo-Json -Compress
    $inventoryResponse = Invoke-RuntimeRequest -Uri 'http://localhost:8080/orders' -Method 'POST' `
        -Body $inventoryBody -ContentType 'application/json' -TimeoutSeconds 5
    Assert-Response -Response $inventoryResponse -Predicate {
        param($response)
        $body = Get-JsonBody -Response $response
        $response.StatusCode -eq 409 -and
            $response.TransportFailure -eq $false -and
            $null -ne $body -and
            $body.success -eq $false -and
            $body.code -eq 'ORDER_BUSINESS_CONFLICT'
    } -FailureMessage '8080 /orders did not return the existing inventory conflict semantics'
    $inventoryResponseBody = Get-JsonBody -Response $inventoryResponse
    $serviceByName['demo-order-8080'].Behavior = [pscustomobject]@{
        Status = 'PASS'
        Method = 'POST'
        Path = '/orders'
        HttpStatus = $inventoryResponse.StatusCode
        SemanticCode = [string]$inventoryResponseBody.code
        ElapsedMs = $inventoryResponse.ElapsedMs
        TransportFailure = $inventoryResponse.TransportFailure
    }

    $webHealth = $serviceByName['apiops-web-19090'].Readiness
    $startupSucceeded = $true
    Write-Stage21State -Status 'READY'

    $summary = [pscustomobject]@{
        SchemaVersion = 'stage21-runtime-world/v2'
        Status = 'READY'
        RunId = $runId
        StartedAt = $startedAt
        ModelCalls = 0
        RuntimeOwner = 'scripts/stage21_start_live_services.ps1'
        CleanupCommand = "powershell.exe -ExecutionPolicy Bypass -File `"$scriptPath`" -Cleanup"
        Infrastructure = @(
            [pscustomobject]@{ Name = 'mysql'; Source = $mysqlSource; Owner = if ($mysqlSource -eq 'docker') { 'docker-compose.dev.yml' } else { 'local MySQL' }; Host = $mysqlReady.Host; HostPort = $mysqlReady.HostPort; Readiness = $mysqlReady }
            [pscustomobject]@{ Name = 'redis'; Owner = 'docker-compose.dev.yml'; HostPort = $redisReady.HostPort; Readiness = $redisReady }
            [pscustomobject]@{ Name = 'rabbitmq'; Owner = 'docker-compose.dev.yml'; HostPort = $rabbitReady.HostPort; Readiness = $rabbitReady }
            [pscustomobject]@{ Name = 'qdrant'; Owner = 'java-apiops-platform/docker-compose.rag.yml'; BaseUrl = $qdrantBaseUrl; Readiness = 'HTTP 200 /healthz' }
        )
        Services = @($services | ForEach-Object {
                $processInfo = Get-ProcessSnapshot -ProcessId $_.ProcessId
                [pscustomobject]@{
                    Name = $_.Name
                    Port = $_.Port
                    Owner = $_.Owner
                    Module = $_.Module
                    ProcessId = $_.ProcessId
                    ProcessOwner = Get-ProcessOwnerName -ProcessInfo $processInfo
                    ProcessCommand = if ($null -ne $processInfo) { [string]$processInfo.CommandLine } else { '' }
                    Readiness = $_.Readiness
                    Behavior = $_.Behavior
                    Stdout = $_.Stdout
                    Stderr = $_.Stderr
                }
            })
        Acceptance = [pscustomobject]@{
            Product18080 = $serviceByName['demo-order-18080'].Behavior
            Fault18081 = $serviceByName['demo-order-18081-fault'].Behavior
            Timeout18082 = $serviceByName['stage21-timeout-target-18082'].Behavior
            Inventory8080 = $serviceByName['demo-order-8080'].Behavior
            ApiOpsWebHealth = $webHealth
            QdrantHealth = 'PASS'
            CoreDependencies = if ($mysqlSource -eq 'docker') {
                'PASS: MySQL/Redis/RabbitMQ compose healthchecks'
            } else {
                'PASS: local MySQL TCP readiness + Redis/RabbitMQ compose healthchecks'
            }
            RedisRequiredReadFixture = $redisFixture
        }
        StatePath = $statePath
        LogRoot = $logRoot
    }
    $summary | ConvertTo-Json -Depth 12
} catch {
    $failureMessage = $_.Exception.Message
} finally {
    if (-not $startupSucceeded) {
        Stop-ManagedServices
        if (Test-Path -LiteralPath $statePath) {
            Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not $startupSucceeded) {
    Write-Error $failureMessage
    exit 1
}
