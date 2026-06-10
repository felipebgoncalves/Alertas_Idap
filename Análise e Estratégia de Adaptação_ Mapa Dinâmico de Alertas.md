# Análise e Estratégia de Adaptação: Mapa Dinâmico de Alertas

Este documento detalha a análise dos projetos "Alertas_Idap" e "mapa-alertas", e propõe uma estratégia para adaptar a funcionalidade de mapa dinâmico do "mapa-alertas" para o projeto "Alertas_Idap".

## 1. Visão Geral dos Projetos

### 1.1. Projeto "Alertas_Idap"

O projeto "Alertas_Idap" [^1] foca na leitura de feeds CAP RSS para alertas no Espírito Santo. Atualmente, ele gera mapas estáticos do estado, plotando as informações dos alertas dentro dos limites municipais. A principal limitação identificada é a incapacidade de lidar eficientemente com polígonos de alerta que abrangem múltiplos municípios, resultando em uma representação estática e menos interativa.

**Componentes Chave:**

*   **Backend (Python - `scripts/idap_daily_maps.py`):**
    *   Processa feeds CAP RSS.
    *   Filtra alertas por `senderName` (Defesa Civil Estadual do Espírito Santo).
    *   Mantém um histórico local de alertas (`.cache/historico_alertas.json`).
    *   Utiliza `geopandas` e `shapely` para manipular dados de polígonos dos alertas CAP.
    *   Gera imagens de mapa estáticas em formato PNG (`mapa_alertas_todos.png`, etc.) usando `matplotlib`.
    *   Utiliza `site/data/geojs-es.json` para os limites municipais.
    *   Produz arquivos JSON de resumo (`alerts_feed.json`, `alerts_24h.json`, `resumo.json`, `resumo.md`).
*   **Frontend (HTML/CSS):**
    *   `site/dashboard.html` e `site/index.html` exibem as imagens PNG estáticas geradas e outros dados sumarizados.

### 1.2. Projeto "mapa-alertas"

link do github: "https://github.com/RicardoBrancoDC/mapa-alertas"

O projeto "mapa-alertas" [^2] oferece uma abordagem mais dinâmica, utilizando o OpenStreetMap como base e plotando os alertas como camadas interativas. Este projeto é mais adequado para visualizar polígonos que cruzam limites municipais, pois permite a interação do usuário com o mapa.

**Componentes Chave:**

*   **Backend (Python - `scripts/fetch_idap.py`, `utils.py`):**
    *   `fetch_idap.py` busca feeds CAP RSS (similar ao "Alertas_Idap").
    *   Analisa o XML CAP, extraindo informações de alerta, incluindo coordenadas de polígonos.
    *   Converte os dados de polígonos para o formato **GeoJSON**.
    *   Salva os dados de alerta processados em arquivos GeoJSON (ex: `inmet_alertas.geojson`) no diretório `data/`.
    *   `utils.py` contém funções auxiliares para manipulação de GeoJSON.
*   **Frontend (HTML/CSS/JavaScript - `index.html`, `assets/js/app.js`, Leaflet.js):**
    *   `index.html` incorpora a biblioteca **Leaflet.js** (`https://unpkg.com/leaflet@1.9.4/dist/leaflet.js`) e um arquivo JavaScript customizado (`assets/js/app.js`).
    *   `assets/js/app.js` é o coração do mapa dinâmico:
        *   Inicializa um mapa Leaflet (`L.map('map')`).
        *   Adiciona camadas base de mapa (tiles do OpenStreetMap).
        *   Busca dados GeoJSON do diretório `data/` (ex: `inmet_alertas.geojson`).
        *   Utiliza `L.geoJSON` para criar camadas Leaflet a partir dos dados GeoJSON.
        *   Define funções `style` e `pointToLayer` para personalizar a aparência de polígonos e marcadores com base nas propriedades do alerta (severidade, tipo).
        *   Implementa `onEachFeature` para vincular popups e tooltips aos elementos do mapa, exibindo informações detalhadas do alerta.
        *   Gerencia a visibilidade das camadas e atualizações com base nos níveis de zoom (ex: para alertas CEMADEN, mostrando estados, depois municípios, depois ícones).
        *   Inclui funções para formatação de datas, normalização de texto e escape de HTML.

## 2. Estratégia de Adaptação para o Projeto "Alertas_Idap"

Para incorporar a funcionalidade de mapa dinâmico do "mapa-alertas" no "Alertas_Idap", as seguintes modificações são necessárias:

### 2.1. Modificações no Backend (Python - `scripts/idap_daily_maps.py`)

1.  **Geração de GeoJSON:**
    *   O script `idap_daily_maps.py` deve ser modificado para, em vez de gerar imagens PNG estáticas com `matplotlib`, processar os polígonos dos alertas CAP e convertê-los para o formato **GeoJSON**.
    *   A função `_parse_polygon_str` já extrai as coordenadas dos polígonos. Essas coordenadas precisam ser estruturadas em uma `FeatureCollection` GeoJSON, com geometrias do tipo `Polygon` e as propriedades relevantes dos alertas (severidade, urgência, descrição, etc.).
    *   Salvar esses dados GeoJSON em um arquivo (ex: `site/data/alertas_idap.geojson`). Este arquivo será consumido pelo frontend.
    *   O projeto "mapa-alertas" já possui um exemplo de como fazer isso em `scripts/fetch_idap.py`, que utiliza a função `write_geojson` de `utils.py` para salvar os dados.

2.  **Remoção de Geração de Imagens Estáticas:**
    *   Remover o código relacionado à geração de mapas estáticos com `matplotlib` e a cópia de PNGs para `site/imagens`, pois o mapa será renderizado dinamicamente no navegador.

### 2.2. Modificações no Frontend (HTML/CSS/JavaScript)

1.  **Atualização do `index.html` (ou `dashboard.html`):**
    *   Incluir a biblioteca **Leaflet.js** e seus estilos CSS. Isso pode ser feito adicionando as seguintes linhas no `<head>` do seu arquivo HTML:
        ```html
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
        ```
    *   Criar um elemento `div` com um `id` específico (ex: `<div id="map"></div>`) onde o mapa Leaflet será renderizado. Este `div` deve ter um tamanho definido via CSS para ser visível.
    *   Incluir um novo arquivo JavaScript (ex: `assets/js/mapa_dinamico.js`) que conterá a lógica de inicialização do mapa e carregamento dos alertas.

2.  **Criação de `assets/js/mapa_dinamico.js` (ou similar):**
    *   **Inicialização do Mapa:** Criar uma instância do mapa Leaflet, definindo a visualização inicial (centro e zoom) e adicionando uma camada base (ex: OpenStreetMap).
        ```javascript
        const map = L.map('map').setView([-19.8153, -40.3378], 8); // Coordenadas do Espírito Santo
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);
        ```
    *   **Carregamento de Dados GeoJSON:** Utilizar a função `fetch` para carregar o arquivo GeoJSON gerado pelo backend (`site/data/alertas_idap.geojson`).
        ```javascript
        fetch('data/alertas_idap.geojson')
            .then(response => response.json())
            .then(geojson_data => {
                // Processar e adicionar os dados GeoJSON ao mapa
            });
        ```
    *   **Estilização e Interatividade:** Implementar as funções de estilização (`style`) e de interação (`onEachFeature`) para os polígonos dos alertas, similar ao `app.js` do projeto "mapa-alertas". Isso inclui:
        *   Definir cores e opacidade para os polígonos com base na severidade do alerta.
        *   Criar popups informativos que aparecem ao clicar nos polígonos, exibindo detalhes do alerta.
        *   Considerar a adição de tooltips para informações rápidas ao passar o mouse.

### 2.3. Estrutura de Dados GeoJSON

O GeoJSON para os alertas deve seguir a estrutura de uma `FeatureCollection`, onde cada `Feature` representa um polígono de alerta e suas propriedades. Exemplo simplificado:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "identifier": "urn:oid:2.49.0.1.840.0.99999.20260603120000.12345",
        "headline": "Alerta de Chuva Forte",
        "description": "Previsão de chuvas intensas nas próximas 24h.",
        "severity": "Severe",
        "urgency": "Immediate",
        "areaDesc": "Municípios X, Y e Z",
        "nivel": "Alto",
        "color": "#ff7f0e" // Cor baseada na severidade
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [[-40.5, -20.0], [-40.0, -20.0], [-40.0, -19.5], [-40.5, -19.5], [-40.5, -20.0]]
        ]
      }
    }
  ]
}
```

## 3. Benefícios da Adaptação

Ao adotar a lógica do "mapa-alertas", o projeto "Alertas_Idap" ganhará as seguintes vantagens:

*   **Interatividade:** Usuários poderão navegar, dar zoom e clicar nos alertas para obter informações detalhadas.
*   **Precisão Geográfica:** A plotagem de polígonos diretamente no mapa dinâmico resolverá o problema de alertas que abrangem múltiplos municípios, mostrando a área exata afetada.
*   **Flexibilidade:** Facilidade para adicionar novas camadas de informação ou integrar outras fontes de dados no futuro.
*   **Experiência do Usuário:** Uma interface mais moderna e intuitiva para a visualização dos alertas.

## Referências

[^1]: [felipebgoncalves/Alertas_Idap](https://github.com/felipebgoncalves/Alertas_Idap)
[^2]: [RicardoBrancoDC/mapa-alertas](https://github.com/RicardoBrancoDC/mapa-alertas)
