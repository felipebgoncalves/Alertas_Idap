$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

Remove-Item Env:NOW_OVERRIDE -ErrorAction SilentlyContinue

$env:RSS_URL = "https://idapfile.mdr.gov.br/idap/api/rss/cap"
$env:OUT_DIR = "out"
$env:HISTORY_PATH = ".cache/historico_alertas.json"
$env:STATE_PATH = ".cache/state.json"
$env:ALERTS_GEOJSON_PATH = "site/data/alertas_idap.geojson"
$env:UF_GEOJSON_PATH = "site/data/geojs-es.json"
$env:MUN_GEOJSON_PATH = "site/data/geojs-es.json"
$env:SITE_DIR = "site"
$env:WINDOW_HOURS = "24"
$env:RETENTION_HOURS = "72"
$env:TARGET_SENDER_NAME = "Defesa Civil Estadual do Espírito Santo"

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
    Invoke-Checked { poetry run python scripts\idap_daily_maps.py } "Coleta CAP/IDAP oficial"
    Invoke-Checked { poetry run python scripts\build_dashboard.py } "Geração do dashboard"
} elseif (Test-Path $venvPython) {
    Invoke-Checked { & $venvPython scripts\idap_daily_maps.py } "Coleta CAP/IDAP oficial"
    Invoke-Checked { & $venvPython scripts\build_dashboard.py } "Geração do dashboard"
} else {
    Invoke-Checked { python scripts\idap_daily_maps.py } "Coleta CAP/IDAP oficial"
    Invoke-Checked { python scripts\build_dashboard.py } "Geração do dashboard"
}
