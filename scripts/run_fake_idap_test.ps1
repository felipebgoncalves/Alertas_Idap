$ErrorActionPreference = "Stop"

$env:RSS_URL = "resources/idap_rss_es_fake.xml"
$env:OUT_DIR = "out/test_fake"
$env:HISTORY_PATH = ".cache/historico_alertas_fake.json"
$env:STATE_PATH = ".cache/state_fake.json"
$env:WINDOW_HOURS = "24"
$env:RETENTION_HOURS = "72"

python scripts\idap_daily_maps.py
