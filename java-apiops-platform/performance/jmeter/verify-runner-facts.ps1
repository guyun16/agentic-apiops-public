param(
    [Parameter(Mandatory = $true)]
    [string] $CasePrefix,
    [Parameter(Mandatory = $true)]
    [long] $ProjectId,
    [int] $WaitSeconds = 30,
    [string] $MysqlPath = 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe',
    [string] $DbHost = 'localhost',
    [string] $DbName = 'apiops_runner',
    [string] $DbUser = 'root'
)

$ErrorActionPreference = 'Stop'
if ($CasePrefix -notmatch '^[A-Za-z0-9_.-]+$') {
    throw 'CasePrefix may contain only letters, digits, underscore, dot, and hyphen.'
}
if (-not (Test-Path -LiteralPath $MysqlPath)) {
    throw "mysql client not found: $MysqlPath"
}
$password = $env:APIOPS_RUNNER_DB_PASSWORD
if ([string]::IsNullOrEmpty($password)) { $password = $env:MYSQL_PWD }
if ([string]::IsNullOrEmpty($password)) {
    throw 'Set APIOPS_RUNNER_DB_PASSWORD (or MYSQL_PWD) in the current shell; it is never printed.'
}

$escapedPrefix = $CasePrefix.Replace("'", "''")
$sql = @"
SELECT t.case_id,
       COUNT(DISTINCT r.id) AS run_count,
       COUNT(DISTINCT cr.id) AS case_result_count,
       GROUP_CONCAT(DISTINCT r.status ORDER BY r.status SEPARATOR ',') AS statuses
FROM test_task t
JOIN test_run r ON r.task_id = t.id AND r.project_id = t.project_id
LEFT JOIN case_result cr ON cr.run_id = r.id AND cr.project_id = r.project_id
WHERE t.project_id = $ProjectId
  AND t.case_id LIKE '$escapedPrefix-%'
GROUP BY t.id, t.case_id
ORDER BY t.id
"@

function Invoke-Query([string] $Query) {
    $env:MYSQL_PWD = $password
    try {
        $arguments = @(
            "--host=$DbHost",
            "--user=$DbUser",
            "--database=$DbName",
            '--batch',
            '--skip-column-names',
            "--execute=$Query"
        )
        return @(& $MysqlPath @arguments 2>&1)
    } finally {
        Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    }
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$rows = @()
$drained = $false
do {
    $rows = @(Invoke-Query $sql)
    if ($rows.Count -gt 0) {
        $nonTerminal = @($rows | Where-Object {
                $parts = $_ -split "`t"
                $parts.Count -ge 4 -and (($parts[3] -split ',') | Where-Object { $_ -in @('PENDING', 'RUNNING') }).Count -gt 0
            })
        if ($nonTerminal.Count -eq 0) {
            $drained = $true
            break
        }
    }
    if ((Get-Date) -ge $deadline) { break }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

if ($rows.Count -eq 0) {
    throw "No runner facts found for case prefix '$CasePrefix'."
}

$allowedStatuses = @(
    'PENDING', 'RUNNING', 'SUCCESS', 'ASSERTION_FAILED',
    'EXECUTION_FAILED', 'TIMEOUT', 'CANCELLED'
)
$duplicateExecutionViolations = @()
$staleRunningViolations = @()
$pendingBacklog = @()
$caseResultViolations = @()
$wrongTerminalStatusViolations = @()
foreach ($row in $rows) {
    $parts = $row -split "`t"
    if ($parts.Count -lt 4) {
        $wrongTerminalStatusViolations += "unparseable row: $row"
        continue
    }
    $caseId = $parts[0]
    $runCount = [int]$parts[1]
    $caseResultCount = [int]$parts[2]
    $statusValues = @($parts[3] -split ',' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $hasPending = @($statusValues | Where-Object { $_ -eq 'PENDING' }).Count -gt 0
    $hasRunning = @($statusValues | Where-Object { $_ -eq 'RUNNING' }).Count -gt 0
    $unexpectedStatuses = @($statusValues | Where-Object { $_ -notin $allowedStatuses })

    # More than one persisted run for one case is duplicate execution evidence.
    # A missing case_result while the run is still PENDING is only backlog.
    if ($runCount -gt 1) {
        $duplicateExecutionViolations += "$caseId run_count=$runCount"
    }
    if ($hasRunning) {
        $staleRunningViolations += "$caseId statuses=$($parts[3])"
    }
    if ($hasPending -and $caseResultCount -eq 0) {
        $pendingBacklog += $caseId
    } elseif ($caseResultCount -ne 1) {
        $caseResultViolations += "$caseId case_result_count=$caseResultCount statuses=$($parts[3])"
    }
    if ($statusValues.Count -eq 0 -or $unexpectedStatuses.Count -gt 0) {
        $wrongTerminalStatusViolations += "$caseId statuses=$($parts[3])"
    }
}

$violations = @(
    $duplicateExecutionViolations
    $staleRunningViolations
    $caseResultViolations
    $wrongTerminalStatusViolations
)
$result = if ($violations.Count -gt 0) {
    'FAIL'
} elseif ($pendingBacklog.Count -gt 0) {
    'PASS_WITH_PENDING_BACKLOG'
} else {
    'PASS'
}

[pscustomobject]@{
    casePrefix = $CasePrefix
    projectId = $ProjectId
    facts = $rows.Count
    drained = $drained
    pendingBacklog = $pendingBacklog.Count
    duplicateExecutionViolations = $duplicateExecutionViolations.Count
    staleRunningViolations = $staleRunningViolations.Count
    caseResultViolations = $caseResultViolations.Count
    wrongTerminalStatusViolations = $wrongTerminalStatusViolations.Count
    violations = $violations
    result = $result
} | ConvertTo-Json -Depth 4

if ($violations.Count -gt 0) { exit 1 }
