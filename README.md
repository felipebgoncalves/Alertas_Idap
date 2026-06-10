# Alertas IDAP - Espírito Santo

Projeto para monitorar alertas CAP publicados no IDAP pela Defesa Civil Estadual do Espírito Santo e publicar um painel estático no GitHub Pages.

## Fluxo

1. `scripts/idap_daily_maps.py` baixa o RSS/CAP, filtra por `senderName`, atualiza o histórico em `.cache/historico_alertas.json`, gera o GeoJSON `site/data/alertas_idap.geojson` e o gráfico em `out/run_*`.
2. O workflow copia apenas o gráfico mais recente para `site/imagens`.
3. `scripts/build_dashboard.py` transforma o histórico em `site/dashboard_data.json`.
4. `site/index.html` renderiza o mapa interativo com Leaflet consumindo `site/data/alertas_idap.geojson`.
5. `site/dashboard.html` segue como dashboard operacional principal.

## Arquivos principais

- `scripts/idap_daily_maps.py`: coleta CAP, histórico, resumo, GeoJSON e gráfico.
- `scripts/build_dashboard.py`: dados agregados do dashboard.
- `site/index.html`: mapa dinâmico principal.
- `site/assets/js/mapa_dinamico.js`: lógica Leaflet do mapa dinâmico.
- `site/dashboard.html`: dashboard operacional principal.
- `site/data/geojs-es.json`: malha municipal do Espírito Santo.
- `site/data/alertas_idap.geojson`: polígonos CAP publicados para o frontend.

## Execução local

```powershell
poetry install
poetry run python scripts\idap_daily_maps.py
poetry run python scripts\build_dashboard.py
python -m http.server 8765 --directory site
```

## Teste com RSS fake

O arquivo `resources/idap_rss_es_fake.xml` combina alertas reais do Espírito Santo no mesmo formato Atom/CAP usado pelo endpoint do IDAP. Para testar o mapa dinâmico sem depender de alertas ativos no RSS oficial:

```powershell
.\scripts\run_fake_idap_test.ps1
```

O teste gera:

- `out/test_fake/run_*/alertas_idap.geojson`
- `site/data/alertas_idap.geojson`
- `out/test_fake/run_*/grafico_alertas_por_hora_24h.png`
