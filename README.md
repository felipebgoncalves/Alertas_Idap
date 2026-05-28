# Alertas IDAP - Espírito Santo

Projeto para monitorar alertas CAP publicados no IDAP pela Defesa Civil Estadual do Espírito Santo e publicar um painel estático no GitHub Pages.

## Fluxo

1. `scripts/idap_daily_maps.py` baixa o RSS/CAP, filtra por `senderName`, atualiza o histórico em `.cache/historico_alertas.json` e gera mapas/gráfico em `out/run_*`.
2. O workflow copia os PNGs mais recentes para `site/imagens`.
3. `scripts/build_dashboard.py` transforma o histórico em `site/dashboard_data.json`.
4. `site/dashboard.html` carrega `dashboard_data.json` e `site/data/geojs-es.json`.

## Arquivos principais

- `scripts/idap_daily_maps.py`: coleta CAP, histórico, resumo e imagens.
- `scripts/build_dashboard.py`: dados agregados do dashboard.
- `site/dashboard.html`: dashboard operacional principal.
- `site/index.html`: galeria dos mapas e gráfico gerados.
- `site/imagens.html`: links diretos para as imagens geradas.
- `site/data/geojs-es.json`: malha municipal do Espírito Santo.

## Execução local

```powershell
poetry install
poetry run python scripts\idap_daily_maps.py
poetry run python scripts\build_dashboard.py
python -m http.server 8765 --directory site
```

## Teste com RSS fake

O arquivo `resources/idap_rss_es_fake.xml` combina tres alertas reais do Espirito Santo no mesmo formato Atom/CAP usado pelo endpoint do IDAP. Para testar a geracao dos mapas sem depender de alertas ativos no RSS oficial:

```powershell
.\scripts\run_fake_idap_test.ps1
```

Os PNGs do teste sao gerados em `out/test_fake`, usando historico e estado separados em `.cache/*_fake.json`.
