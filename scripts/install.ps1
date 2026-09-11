param([ValidateSet('product', 'research')][string]$Edition = 'product')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskManifestPath = Join-Path $taskRoot 'edition-manifest.json'
if (Test-Path -LiteralPath $taskManifestPath) {
    $taskManifest = Get-Content -LiteralPath $taskManifestPath -Raw | ConvertFrom-Json
    if (-not $PSBoundParameters.ContainsKey('Edition')) { $Edition = $taskManifest.edition }
    if ($Edition -eq 'research' -and -not $taskManifest.research_available) {
        throw 'This product archive has no research modules. Obtain the research source archive.'
    }
}
Push-Location (Join-Path $taskRoot 'backend')
try {
    if ($Edition -eq 'research') { uv sync --frozen --no-dev --group research }
    else { uv sync --frozen --no-dev }
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $taskRoot 'frontend')
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally { Pop-Location }
Write-Output "Dependencies ready for $Edition. Set AGENTIC_EDITION=$Edition in .env."
Write-Output 'No model weights or benchmark datasets were downloaded. Follow README to migrate and start.'
