param(
    [Parameter(Mandatory = $true)]
    [string] $JtlPath,
    [string] $LabelRegex = '',
    [string] $OutputPath = ''
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $JtlPath)) {
    throw "JTL not found: $JtlPath"
}

$rows = @(Import-Csv -LiteralPath $JtlPath)
if ($LabelRegex) {
    $rows = @($rows | Where-Object { $_.label -match $LabelRegex })
}
if ($rows.Count -eq 0) {
    throw "No samples matched the requested JTL/label filter."
}

$samples = @($rows | ForEach-Object {
        [pscustomobject]@{
            timestamp = [long]$_.timeStamp
            elapsed = [double]$_.elapsed
            success = ([string]$_.success).ToLowerInvariant() -eq 'true'
        }
    })
$latencies = @($samples | ForEach-Object { $_.elapsed } | Sort-Object)
$errorCount = @($samples | Where-Object { -not $_.success }).Count
$spanMs = ([double]$samples[-1].timestamp - [double]$samples[0].timestamp)
if ($spanMs -lt 1) { $spanMs = 1 }

function Get-NearestRankPercentile([double[]] $values, [double] $quantile) {
    $rank = [math]::Ceiling($values.Count * $quantile)
    if ($rank -lt 1) { $rank = 1 }
    return [double]$values[$rank - 1]
}

$summary = [ordered]@{
    jtl = (Resolve-Path -LiteralPath $JtlPath).Path
    labelRegex = $LabelRegex
    samples = $samples.Count
    errors = $errorCount
    errorRatePercent = [math]::Round(($errorCount * 100.0) / $samples.Count, 4)
    throughputSamplesPerSecond = [math]::Round(($samples.Count * 1000.0) / $spanMs, 4)
    averageMs = [math]::Round(($latencies | Measure-Object -Average).Average, 4)
    p95Ms = [math]::Round((Get-NearestRankPercentile $latencies 0.95), 4)
    p99Ms = [math]::Round((Get-NearestRankPercentile $latencies 0.99), 4)
    firstTimestampUtc = [DateTimeOffset]::FromUnixTimeMilliseconds($samples[0].timestamp).UtcDateTime.ToString('o')
    lastTimestampUtc = [DateTimeOffset]::FromUnixTimeMilliseconds($samples[-1].timestamp).UtcDateTime.ToString('o')
}

$json = [pscustomobject]$summary | ConvertTo-Json -Depth 4
if ($OutputPath) {
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8
}
$json
