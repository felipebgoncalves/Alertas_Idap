param(
    [switch]$PublishToSite
)

$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

$env:RSS_URL = "resources/idap_rss_es_fake.xml"
$env:OUT_DIR = "out/test_fake"
$env:HISTORY_PATH = ".cache/historico_alertas_fake.json"
$env:STATE_PATH = ".cache/state_fake.json"
$env:WINDOW_HOURS = "24"
$env:RETENTION_HOURS = "72"
$env:NOW_OVERRIDE = "2026-06-08T16:50:00-03:00"
$env:TARGET_SENDER_NAME = "Defesa Civil Estadual do Espírito Santo"

if ($PublishToSite) {
    $env:SITE_DIR = "site"
    $env:ALERTS_GEOJSON_PATH = "site/data/alertas_idap.geojson"
} else {
    $env:SITE_DIR = "out/test_fake/site"
    $env:ALERTS_GEOJSON_PATH = "out/test_fake/site/data/alertas_idap.geojson"

    New-Item -ItemType Directory -Force -Path $env:SITE_DIR, (Join-Path $env:SITE_DIR "data") | Out-Null
    Copy-Item -LiteralPath "site\dashboard.html", "site\index.html", "site\imagens.html" -Destination $env:SITE_DIR -Force
    Copy-Item -LiteralPath "site\assets" -Destination $env:SITE_DIR -Recurse -Force
    Copy-Item -LiteralPath "site\data\geojs-es.json" -Destination (Join-Path $env:SITE_DIR "data\geojs-es.json") -Force
}

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description falhou com código $LASTEXITCODE"
    }
}

if (Get-Command poetry -ErrorAction SilentlyContinue) {
    Invoke-Checked { poetry run python scripts\idap_daily_maps.py } "Coleta CAP/IDAP fake"
    Invoke-Checked { poetry run python scripts\build_dashboard.py } "Geração do dashboard fake"
} elseif (Test-Path $venvPython) {
    Invoke-Checked { & $venvPython scripts\idap_daily_maps.py } "Coleta CAP/IDAP fake"
    Invoke-Checked { & $venvPython scripts\build_dashboard.py } "Geração do dashboard fake"
} else {
    Invoke-Checked { python scripts\idap_daily_maps.py } "Coleta CAP/IDAP fake"
    Invoke-Checked { python scripts\build_dashboard.py } "Geração do dashboard fake"
}
