[CmdletBinding()]
param([switch]$SkipStart)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo '.local-run/hr-demo'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if (-not $SkipStart) {
    & (Join-Path $PSScriptRoot 'start-project.ps1') -NoBrowser
    if ($LASTEXITCODE -ne 0) { throw 'Project startup failed.' }
}
$credentials = Join-Path $runtime '.env.local'
if (-not (Test-Path -LiteralPath $credentials)) {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $lines = foreach ($key in @('HR_PRESENTER_PASSWORD', 'HR_VIEWER_PASSWORD')) {
            $bytes = New-Object byte[] 24
            $rng.GetBytes($bytes)
            $key + '=' + [Convert]::ToBase64String($bytes)
        }
        $lines | Set-Content -LiteralPath $credentials -Encoding UTF8
    } finally { $rng.Dispose() }
}
$saved = @{}
try {
    foreach ($file in @((Join-Path $repo '.env.local'), $credentials)) {
        foreach ($line in Get-Content -LiteralPath $file) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
                $key = $Matches[1]
                if (-not $saved.ContainsKey($key)) { $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process') }
                [Environment]::SetEnvironmentVariable($key, $Matches[2].Trim(), 'Process')
            }
        }
    }
    foreach ($key in @('APIOPS_AUTH_DB_URL', 'APIOPS_AUTH_DB_USERNAME', 'APIOPS_AUTH_DB_PASSWORD')) {
        if (-not $saved.ContainsKey($key)) { $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process') }
    }
    if (-not $env:APIOPS_AUTH_DB_URL) { $env:APIOPS_AUTH_DB_URL = 'jdbc:mysql://127.0.0.1:3306/apiops_auth' }
    if (-not $env:APIOPS_AUTH_DB_USERNAME) { $env:APIOPS_AUTH_DB_USERNAME = 'root' }
    if (-not $env:APIOPS_AUTH_DB_PASSWORD) { $env:APIOPS_AUTH_DB_PASSWORD = $env:APIOPS_STAGE21_DB_PASSWORD }
    $maven = Join-Path $env:USERPROFILE '.m2/repository'
    $jars = foreach ($entry in @('org/springframework/security/spring-security-crypto', 'org/springframework/spring-jcl', 'com/mysql/mysql-connector-j')) {
        $jar = Get-ChildItem -LiteralPath (Join-Path $maven $entry) -Recurse -Filter '*.jar' |
            Where-Object Name -NotMatch '(sources|javadoc)' | Sort-Object FullName -Descending | Select-Object -First 1
        if (-not $jar) { throw "Missing Maven dependency: $entry. Build Java first." }
        $jar.FullName
    }
    $identity = & java.exe --class-path ($jars -join [IO.Path]::PathSeparator) (Join-Path $PSScriptRoot 'hr-demo/ProvisionHrDemo.java')
    if ($LASTEXITCODE -ne 0) { throw 'Demo identity setup failed.' }
    $identity | Set-Content -LiteralPath (Join-Path $runtime 'identity.json') -Encoding UTF8
    & (Join-Path $repo 'python-apiops-agentlab/.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'hr-demo/seed.py')
    if ($LASTEXITCODE -ne 0) { throw 'Demo data verification failed.' }
    Write-Host "HR demo ready. Private credentials: $credentials"
} finally {
    foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
}
