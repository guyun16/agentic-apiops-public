[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$BaseUrl
)

Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$targetDirectory = Join-Path $repositoryRoot 'docs\openapi'
$targetPath = Join-Path $targetDirectory 'demo-order-service-openapi.json'

try {
    $trimmedBaseUrl = $BaseUrl.TrimEnd('/')
    $baseUri = [System.Uri]::new($trimmedBaseUrl)
    if (-not $baseUri.IsAbsoluteUri -or $baseUri.Scheme -notin @('http', 'https')) {
        throw 'BaseUrl must be an absolute HTTP or HTTPS URL.'
    }

    $apiDocsUri = [System.Uri]::new($trimmedBaseUrl + '/v3/api-docs')
    $response = Invoke-WebRequest `
        -Uri $apiDocsUri `
        -Method Get `
        -Headers @{ Accept = 'application/json' } `
        -UseBasicParsing `
        -ErrorAction Stop

    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw 'OpenAPI endpoint returned a non-success HTTP status.'
    }

    $openApiDocument = $response.Content | ConvertFrom-Json -ErrorAction Stop
    $serializedDocument = $openApiDocument | ConvertTo-Json -Depth 100

    [System.IO.Directory]::CreateDirectory($targetDirectory) | Out-Null
    [System.IO.File]::WriteAllText(
        $targetPath,
        $serializedDocument + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false))

    Write-Output 'OpenAPI export succeeded.'
    Write-Output 'Target: docs/openapi/demo-order-service-openapi.json'
}
catch {
    Write-Error ('OpenAPI export failed: ' + $_.Exception.GetType().Name)
    exit 1
}
