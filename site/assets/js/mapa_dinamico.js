(function () {
  const GEOJSON_URL = "./data/alertas_idap.geojson";
  const UPDATE_URL = "./ultima_atualizacao.json";

  const elements = {
    update: document.getElementById("ultima-atualizacao"),
    error: document.getElementById("mensagem-erro"),
    empty: document.getElementById("sem-alertas"),
    total: document.getElementById("metric-total"),
    features: document.getElementById("metric-features"),
    municipios: document.getElementById("metric-municipios"),
  };

  const map = L.map("mapa-alertas", {
    zoomControl: true,
    attributionControl: true,
  }).setView([-19.55, -40.62], 8);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function repairText(value) {
    const text = String(value ?? "");
    if (!text.includes("Ã") && !text.includes("Â")) {
      return text;
    }

    try {
      return decodeURIComponent(escape(text));
    } catch (error) {
      return text;
    }
  }

  function formatDescription(text) {
    if (!text) {
      return "Sem descrição detalhada.";
    }
    const clean = repairText(text).trim();
    return clean.length > 320 ? `${clean.slice(0, 317)}...` : clean;
  }

  function popupHtml(props) {
    const nivel = escapeHtml(repairText(props.nivel || "Indefinido"));
    const evento = escapeHtml(repairText(props.event || props.headline || "Alerta"));
    const emissor = escapeHtml(repairText(props.senderName || "Defesa Civil Estadual do ES"));
    const municipio = escapeHtml(repairText(props.municipio_nome || props.areaDesc || "Área informada no alerta"));
    const expira = escapeHtml(repairText(props.expires_label || "Não informado"));
    const inicio = escapeHtml(repairText(props.onset_label || props.sent_label || "Não informado"));
    const descricao = escapeHtml(formatDescription(props.description));

    return `
      <div class="popup">
        <h3>${evento}</h3>
        <div class="popup-meta">
          <span class="tag">${nivel}</span>
          <span class="tag">${municipio}</span>
        </div>
        <div><strong>Emissor:</strong> ${emissor}</div>
        <div><strong>Início:</strong> ${inicio}</div>
        <div><strong>Expira:</strong> ${expira}</div>
        <div>${descricao}</div>
      </div>
    `;
  }

  function updateMetrics(collection) {
    const features = Array.isArray(collection.features) ? collection.features : [];
    const municipios = new Set();

    features.forEach((feature) => {
      const nome = feature?.properties?.municipio_nome;
      if (nome) {
        municipios.add(nome);
      }
    });

    elements.total.textContent = String(collection.total_alerts ?? features.length);
    elements.features.textContent = String(features.length);
    elements.municipios.textContent = String(municipios.size);
  }

  async function loadUpdateInfo() {
    try {
      const response = await fetch(`${UPDATE_URL}?ts=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error("ultima_atualizacao.json não disponível");
      }

      const data = await response.json();
      const raw = data?.gerado_em;
      if (!raw) {
        throw new Error("Campo gerado_em ausente");
      }

      const date = new Date(raw);
      elements.update.textContent = date.toLocaleString("pt-BR", {
        dateStyle: "short",
        timeStyle: "medium",
      });
    } catch (error) {
      elements.update.textContent = "não disponível";
      elements.error.style.display = "block";
    }
  }

  async function loadMap() {
    try {
      const response = await fetch(`${GEOJSON_URL}?ts=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error("GeoJSON não encontrado");
      }

      const data = await response.json();
      const features = Array.isArray(data.features) ? data.features : [];

      updateMetrics(data);

      if (!features.length) {
        elements.empty.style.display = "block";
        return;
      }

      const layer = L.geoJSON(data, {
        style(feature) {
          const color = feature?.properties?.color || "#2563eb";
          return {
            color,
            weight: 2,
            fillColor: color,
            fillOpacity: 0.32,
          };
        },
        onEachFeature(feature, currentLayer) {
          currentLayer.bindPopup(popupHtml(feature.properties || {}), {
            maxWidth: 360,
          });
        },
      }).addTo(map);

      const bounds = layer.getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [20, 20] });
      }
    } catch (error) {
      elements.error.style.display = "block";
      elements.error.textContent = `Não foi possível carregar o mapa dinâmico: ${error.message}`;
    }
  }

  loadUpdateInfo();
  loadMap();
})();
