# Para rodar manualmente com dados fake sem alterar o site de produção:

    .\scripts\run_fake_idap_test.ps1

## Isso gera os arquivos fake em:

    out/test_fake/site/dashboard_data.json
    out/test_fake/site/data/alertas_idap.geojson

## Para visualizar no navegador:

    python -m http.server 8765 --directory out/test_fake/site


## Depois acesse:

    http://localhost:8765/dashboard.html

## Se você quiser jogar os dados fake diretamente dentro da pasta site/ para testar o layout principal:

    .\scripts\run_fake_idap_test.ps1 -PublishToSite
    python -m http.server 8765 --directory site

## Depois de usar -PublishToSite, antes de fazer commit rode produção de novo:

    .\scripts\run_production.ps1