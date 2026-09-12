[CmdletBinding()]
param(
    [string]$HostName = '127.0.0.1',
    [int]$Port = 3306,
    [string]$Username = 'root',
    [string]$Password = $env:APIOPS_STAGE21_DB_PASSWORD
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$schema = Join-Path $repo 'java-apiops-platform\apiops-runner\src\main\resources\db\runner-schema.sql'
$mysql = (Get-Command mysql.exe -ErrorAction Stop).Source
$previousPassword = [Environment]::GetEnvironmentVariable('MYSQL_PWD', 'Process')

try {
    $env:MYSQL_PWD = $Password
    # All statements are CREATE TABLE IF NOT EXISTS; existing execution facts remain intact.
    Get-Content -LiteralPath $schema -Raw | & $mysql -h $HostName -P $Port -u $Username apiops_runner
    if ($LASTEXITCODE -ne 0) { throw 'Could not apply runner-schema.sql.' }
} finally {
    [Environment]::SetEnvironmentVariable('MYSQL_PWD', $previousPassword, 'Process')
}

Write-Host "Applied Runner schema to ${HostName}:$Port/apiops_runner."
