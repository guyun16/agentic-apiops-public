[CmdletBinding()]
param(
    [string]$HostName = '127.0.0.1',
    [int]$Port = 3306,
    [string]$Username = 'root',
    [string]$Password = $env:APIOPS_STAGE21_DB_PASSWORD
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$schema = Join-Path $repo 'java-apiops-platform\apiops-tool-gateway\src\main\resources\db\tool-gateway-schema.sql'
$mysql = (Get-Command mysql.exe -ErrorAction Stop).Source
$previousPassword = [Environment]::GetEnvironmentVariable('MYSQL_PWD', 'Process')

try {
    $env:MYSQL_PWD = $Password
    & $mysql -h $HostName -P $Port -u $Username -e `
        'CREATE DATABASE IF NOT EXISTS apiops_tool_gateway CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;'
    if ($LASTEXITCODE -ne 0) { throw 'Could not create or select apiops_tool_gateway.' }

    Get-Content -LiteralPath $schema -Raw | & $mysql -h $HostName -P $Port -u $Username apiops_tool_gateway
    if ($LASTEXITCODE -ne 0) { throw 'Could not apply tool-gateway-schema.sql.' }
} finally {
    [Environment]::SetEnvironmentVariable('MYSQL_PWD', $previousPassword, 'Process')
}

Write-Host "Applied Tool Gateway schema to ${HostName}:$Port/apiops_tool_gateway."
