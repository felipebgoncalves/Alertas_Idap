$ErrorActionPreference = "Stop"

$env:RSS_URL = "resources/idap_rss_es_fake.xml"
$env:OUT_DIR = "out/test_fake"
$env:HISTORY_PATH = ".cache/historico_alertas_fake.json"
$env:STATE_PATH = ".cache/state_fake.json"
$env:ALERTS_GEOJSON_PATH = "site/data/alertas_idap.geojson"
$env:WINDOW_HOURS = "24"
$env:RETENTION_HOURS = "72"
$env:NOW_OVERRIDE = "2026-06-08T16:50:00-03:00"

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"

if (Get-Command poetry -ErrorAction SilentlyContinue) {
    poetry run python scripts\idap_daily_maps.py
    poetry run python scripts\build_dashboard.py
} elseif (Test-Path $venvPython) {
    & $venvPython scripts\idap_daily_maps.py
    & $venvPython scripts\build_dashboard.py
} else {
    python scripts\idap_daily_maps.py
    python scripts\build_dashboard.py
}
