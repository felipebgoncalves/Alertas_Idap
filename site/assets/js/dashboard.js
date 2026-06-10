const AUTO_REFRESH_MS = 60000;
const LEVEL_COLORS = {
  Extremo: "#6c4ce6",
  Severo: "#e23d2f",
  Alto: "#ea8f1c",
  Médio: "#e3b620",
  Baixo: "#2f9e59",
  Indefinido: "#8a96aa",
};

let refreshSecondsRemaining = Math.floor(AUTO_REFRESH_MS / 1000);
let recentAlerts = [];
let dashboardMap = null;
let dashboardAlertasLayer = null;

document.addEventListener("DOMContentLoaded", () => {
  carregarDashboard();
  iniciarTimerRefresh();
  setInterval(carregarDashboard, AUTO_REFRESH_MS);
});

async function carregarDashboard() {
  try {
    const response = await fetch(`dashboard_data.json?_=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Falha ao carregar dashboard_data.json: ${response.status}`);

    const data = await response.json();
    const alerts = (data.all_alerts || data.latest_alerts || []).map(normalizarAlerta);
    const latest = (data.latest_alerts || alerts).map(normalizarAlerta);

    refreshSecondsRemaining = Math.floor(AUTO_REFRESH_MS / 1000);
    preencherCabecalho(data);
    preencherRotulosPeriodo(data);
    preencherCards(data, alerts);
    renderUltimosAlertas(alerts.length ? alerts : latest, data);
    renderMapaMunicipal(data);
    renderSeveridade(alerts, data.level_distribution || []);
    renderEventos(alerts, data.event_distribution || []);
    renderHoras(alerts, data.generated_at);
  } catch (error) {
    console.error("Erro geral do dashboard:", error);
    renderErroGeral();
  }
}

function preencherCabecalho(data) {
  setText("meta-atualizado", formatarDataHora(data.generated_at));
}

function preencherRotulosPeriodo(data) {
  const label = formatarJanelaDados(data);
  setText("label-periodo-alertas", label);
  setText("titulo-alertas-hora", `Alertas ${formatarJanelaComPreposicao(data)}`);
}

function preencherCards(data, alerts) {
  const levels = contar(alerts, "nivel");
  const vigentes = numeroBruto(data.cards?.vigentes ?? alerts.filter(estaVigente).length);
  const total = numeroBruto(data.cards?.ultimas24h ?? alerts.length);
  const graves = numeroBruto(data.cards?.alertasSeverosExtremos ?? ((levels.Severo || 0) + (levels.Extremo || 0)));
  const municipios = numeroBruto(data.cards?.municipiosComAlertas ?? data.cards?.municipiosOuAreasComAlerta ?? contarMunicipios(alerts));

  setText("card-24h", numero(total));
  setText("card-vigentes", numero(vigentes));
  setText("card-autoridades", numero(graves));
  setText("card-tipos-evento", numero(municipios));
}

function renderUltimosAlertas(alertas, data) {
  const container = byId("ultimos-alertas");
  if (!container) return;

  recentAlerts = Array.isArray(alertas) ? alertas : [];

  if (!recentAlerts.length) {
    container.innerHTML = `<div class="empty-state">Nenhum alerta estadual do ES ${esc(formatarJanelaComPreposicao(data))}.</div>`;
    return;
  }

  renderPaginaUltimosAlertas();
}

function renderPaginaUltimosAlertas() {
  const container = byId("ultimos-alertas");
  if (!container) return;

  container.innerHTML = recentAlerts.map((alerta) => `
    <div class="recent-item">
      <div class="recent-time">
        <div class="recent-time-hour">${esc(alerta.time || formatarHora(alerta.sent))}</div>
        <div class="recent-time-date">${esc(alerta.date || formatarData(alerta.sent))}</div>
      </div>
      <div class="recent-emissor">
        <div class="recent-emissor-name" title="${escAttr(alerta.senderName)}">${esc(alerta.senderNameShort || alerta.senderName)}</div>
        <div class="recent-emissor-loc" title="${escAttr(formatarMunicipiosAfetados(alerta))}">${esc(formatarMunicipiosAfetados(alerta))}</div>
      </div>
      <div class="recent-content">
        <div class="recent-evento">${esc(titulo(alerta.event))}</div>
        <div class="recent-desc">${esc(truncar(alerta.headline || alerta.description || alerta.areaDesc || "Sem descrição disponível.", 150))}</div>
      </div>
      <div class="recent-status">
        <div class="recent-tag ${classeNivel(alerta.nivel)}">${esc(alerta.nivel)}</div>
        <div class="recent-expira">
          <span class="recent-expira-label">Expira:</span>
          <span class="recent-expira-value">${esc(formatarExpiracaoValor(alerta))}</span>
        </div>
      </div>
    </div>
  `).join("");
}

async function renderMapaMunicipal(data) {
  const container = byId("mapa-uf");
  if (!container) return;

  if (!window.L) {
    container.innerHTML = `<div class="empty-state">Mapa dinâmico indisponível.</div>`;
    return;
  }

  try {
    const timestamp = Date.now();
    const alertasUrl = data.geo?.alertas_geojson || "data/alertas_idap.geojson";

    const alertasResponse = await fetch(`${alertasUrl}?_=${timestamp}`, { cache: "no-store" });

    if (!alertasResponse.ok) throw new Error(`Falha ao carregar GeoJSON de alertas: ${alertasResponse.status}`);

    const alertasGeojson = await alertasResponse.json();

    inicializarMapaDashboard(container);
    atualizarCamadasMapaDashboard(alertasGeojson);
  } catch (error) {
    console.error("Erro ao renderizar mapa dinâmico:", error);
    container.innerHTML = `<div class="empty-state">Mapa dinâmico indisponível.</div>`;
    dashboardMap = null;
    dashboardAlertasLayer = null;
  }
}

function inicializarMapaDashboard(container) {
  if (dashboardMap) {
    setTimeout(() => dashboardMap.invalidateSize(), 60);
    return;
  }

  container.innerHTML = "";
  dashboardMap = L.map(container, {
    zoomControl: true,
    attributionControl: true,
  }).setView([-19.55, -40.62], 8);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(dashboardMap);

  setTimeout(() => dashboardMap.invalidateSize(), 80);
}

function atualizarCamadasMapaDashboard(alertasGeojson) {
  if (!dashboardMap) return;

  if (dashboardAlertasLayer) dashboardAlertasLayer.remove();

  const features = Array.isArray(alertasGeojson?.features) ? alertasGeojson.features : [];

  dashboardAlertasLayer = L.geoJSON(alertasGeojson || { features: [] }, {
    style(feature) {
      const color = feature?.properties?.color || "#2563eb";

      return {
        color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.32,
      };
    },
    onEachFeature(feature, layer) {
      layer.bindPopup(popupMapaDashboard(feature.properties || {}), {
        maxWidth: 360,
      });
    },
  }).addTo(dashboardMap);

  if (!features.length) {
    dashboardMap.setView([-19.55, -40.62], 8);
    setTimeout(() => dashboardMap.invalidateSize(), 80);
    return;
  }

  const bounds = dashboardAlertasLayer.getBounds();
  if (bounds.isValid()) {
    dashboardMap.fitBounds(bounds, { padding: [20, 20] });
  }

  setTimeout(() => dashboardMap.invalidateSize(), 80);
}

function popupMapaDashboard(props) {
  const nivel = esc(repairText(props.nivel || "Indefinido"));
  const evento = esc(repairText(props.event || props.headline || "Alerta"));
  const emissor = esc(repairText(props.senderName || "Defesa Civil Estadual do ES"));
  const expira = esc(repairText(props.expires_label || "Não informado"));
  const inicio = esc(repairText(props.onset_label || props.sent_label || "Não informado"));
  const descricao = esc(formatarDescricaoMapa(props.description));

  return `
    <div class="popup">
      <h3>${evento}</h3>
      <div class="popup-meta">
        <span class="tag">${nivel}</span>
      </div>
      <div><strong>Emissor:</strong> ${emissor}</div>
      <div><strong>Início:</strong> ${inicio}</div>
      <div><strong>Expira:</strong> ${expira}</div>
      <div>${descricao}</div>
    </div>
  `;
}

function formatarDescricaoMapa(text) {
  if (!text) return "Sem descrição detalhada.";
  const clean = repairText(text).trim();
  return clean.length > 320 ? `${clean.slice(0, 317)}...` : clean;
}

function repairText(value) {
  const text = String(value ?? "");
  if (!text.includes("Ã") && !text.includes("Â")) return text;

  try {
    return decodeURIComponent(escape(text));
  } catch (error) {
    return text;
  }
}

function renderSeveridade(alerts, distribution) {
  const container = byId("severity-breakdown");
  if (!container) return;

  const values = distribuicaoParaMapa(distribution);
  if (!Object.keys(values).length) Object.assign(values, contar(alerts, "nivel"));

  const order = ["Baixo", "Médio", "Alto", "Severo", "Extremo"];
  const max = Math.max(...order.map((nivel) => values[nivel] || 0), 1);
  const classes = { Baixo: "sev-c1", Médio: "sev-c2", Alto: "sev-c3", Severo: "sev-c4", Extremo: "sev-c5" };

  container.innerHTML = order.map((nivel) => {
    const value = values[nivel] || 0;
    const pct = value > 0 ? Math.max((value / max) * 100, 4) : 0;
    return `
      <div class="severity-row">
        <div class="severity-row-head">
          <div class="severity-row-name">${nivel}</div>
          <div class="severity-row-value">${numero(value)}</div>
        </div>
        <div class="severity-track"><div class="severity-fill ${classes[nivel]}" style="width:${pct}%;"></div></div>
      </div>
    `;
  }).join("");
}

function renderEventos(alerts, distribution) {
  const container = byId("event-breakdown");
  if (!container) return;

  let rows = (distribution || []).map((item) => ({
    label: item.label || item.event || "Sem evento",
    count: numeroBruto(item.count),
  }));

  if (!rows.length) {
    rows = Object.entries(contar(alerts, "event"))
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count);
  }

  if (!rows.length) {
    container.innerHTML = `<div class="empty-state">Nenhum evento disponível.</div>`;
    return;
  }

  const classes = ["event-c1", "event-c2", "event-c3", "event-c4", "event-c5"];
  const max = Math.max(...rows.map((row) => row.count), 1);

  container.innerHTML = rows.slice(0, 5).map((row, index) => {
    const pct = row.count > 0 ? Math.max((row.count / max) * 100, 8) : 0;
    return `
      <div class="event-row">
        <div class="event-row-head">
          <div class="event-row-name" title="${escAttr(row.label)}">${esc(titulo(row.label))}</div>
          <div class="event-row-value">${numero(row.count)}</div>
        </div>
        <div class="event-track"><div class="event-fill ${classes[index] || "event-c5"}" style="width:${pct}%;"></div></div>
      </div>
    `;
  }).join("");
}

function renderHoras(alerts, referenceIso) {
  const container = byId("hourly-breakdown");
  if (!container) return;

  const ref = dataValida(referenceIso) || maiorData(alerts) || new Date();
  const buckets = [];
  for (let i = 23; i >= 0; i -= 1) {
    const date = new Date(ref.getTime() - i * 3600000);
    buckets.push({ key: chaveHora(date), label: formatarHora(date), count: 0 });
  }

  alerts.forEach((alerta) => {
    const date = dataValida(alerta.sent || alerta.onset);
    if (!date) return;
    const key = chaveHora(date);
    const bucket = buckets.find((item) => item.key === key);
    if (bucket) bucket.count += 1;
  });

  const max = Math.max(...buckets.map((bucket) => bucket.count), 1);
  const bars = buckets.map((bucket) => {
    const height = bucket.count > 0 ? Math.max((bucket.count / max) * 100, 6) : 0;
    return `
      <div class="hourly-bar-col" title="${esc(bucket.label)}: ${numero(bucket.count)} alerta(s)">
        <div class="hourly-bar-value">${bucket.count || ""}</div>
        <div class="hourly-bar" style="height:${height}%; opacity:${bucket.count ? 1 : 0.14};"></div>
      </div>
    `;
  }).join("");
  const labels = buckets.map((bucket, index) => `<div class="${index % 2 ? "hourly-label muted" : "hourly-label"}">${esc(bucket.label)}</div>`).join("");

  container.innerHTML = `
    <div class="hourly-chart">
      <div class="hourly-grid">${Array.from({ length: 4 }).map(() => `<div class="hourly-grid-line"></div>`).join("")}</div>
      <div class="hourly-bars">${bars}</div>
      <div class="hourly-labels">${labels}</div>
    </div>
  `;
}

function normalizarAlerta(alerta) {
  const locationInfo = extrairMunicipio(alerta.location || alerta.areaDesc);
  const senderName = alerta.senderName || alerta.sender || "Defesa Civil Estadual do Espírito Santo";
  const sent = alerta.sent || alerta.onset || alerta.sent_iso || alerta.datetime;
  const affected = normalizarMunicipiosAfetados(alerta);

  return {
    ...alerta,
    senderName,
    senderNameShort: alerta.senderNameShort || abreviarEmissor(senderName),
    sent,
    uf: String(alerta.uf || alerta.uf_hint || locationInfo.uf || "ES").toUpperCase(),
    municipio_id: String(alerta.municipio_id || ""),
    municipio_nome: alerta.municipio_nome || affected[0]?.municipio_nome || locationInfo.city || "",
    event: alerta.event_short || alerta.event || alerta.evento || "Sem evento",
    nivel: normalizarNivel(alerta.nivel || alerta.severity || "Indefinido"),
    location: alerta.location || alerta.municipio_nome || alerta.areaDesc || "Espírito Santo",
    category: alerta.category || inferirCategoria(alerta.event || alerta.evento),
    affected_municipios: affected,
  };
}

function contarMunicipios(alerts) {
  const values = new Set();
  alerts.forEach((alerta) => {
    const municipios = normalizarMunicipiosAfetados(alerta);
    if (municipios.length) {
      municipios.forEach((municipio) => {
        const key = municipio.municipio_id || municipio.municipio_nome || "";
        if (key) values.add(key);
      });
      return;
    }

    const key = alerta.municipio_id || alerta.municipio_nome || "";
    if (key) values.add(key);
  });
  return values.size;
}

function normalizarMunicipiosAfetados(alerta) {
  const raw = Array.isArray(alerta?.affected_municipios) ? alerta.affected_municipios : [];
  const names = Array.isArray(alerta?.affected_municipio_names) ? alerta.affected_municipio_names : [];
  const ids = Array.isArray(alerta?.affected_municipio_ids) ? alerta.affected_municipio_ids : [];
  const seen = new Set();
  const output = [];

  raw.forEach((item) => {
    const municipio_id = String(item?.municipio_id || item?.codigo_ibge || item?.id || "").trim();
    const municipio_nome = repairText(item?.municipio_nome || item?.nome || item?.name || "").trim();
    const key = municipio_id || slug(municipio_nome);
    if (!key || seen.has(key)) return;
    seen.add(key);
    output.push({ municipio_id, municipio_nome });
  });

  names.forEach((name, index) => {
    const municipio_nome = repairText(name).trim();
    const municipio_id = String(ids[index] || "").trim();
    const key = municipio_id || slug(municipio_nome);
    if (!key || seen.has(key)) return;
    seen.add(key);
    output.push({ municipio_id, municipio_nome });
  });

  return output;
}

function formatarMunicipiosAfetados(alerta) {
  const municipios = normalizarMunicipiosAfetados(alerta)
    .map((municipio) => municipio.municipio_nome)
    .filter(Boolean);

  if (municipios.length) return municipios.join(", ");
  return alerta.municipio_nome || alerta.location || "Espírito Santo";
}

function contar(array, key) {
  const values = {};
  (array || []).forEach((item) => {
    const label = typeof key === "function" ? key(item) : item[key];
    const finalLabel = label || "Sem informação";
    values[finalLabel] = (values[finalLabel] || 0) + 1;
  });
  return values;
}

function distribuicaoParaMapa(distribution) {
  const values = {};
  (distribution || []).forEach((item) => {
    values[item.label || item.name || "Sem informação"] = numeroBruto(item.count || item.total || item.valor);
  });
  return values;
}

function estaVigente(alerta) {
  const status = String(alerta.status || alerta.status_vigencia || "").toLowerCase();
  if (status.includes("vigente")) return true;
  if (status.includes("expirado")) return false;
  const expires = dataValida(alerta.expires);
  return Boolean(expires && expires > new Date());
}

function normalizarNivel(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("extremo") || text === "extreme") return "Extremo";
  if (text.includes("severo")) return "Severo";
  if (text.includes("alto") || text === "severe") return "Alto";
  if (text.includes("médio") || text.includes("medio") || text === "moderate") return "Médio";
  if (text.includes("baixo") || text === "minor") return "Baixo";
  return "Indefinido";
}

function classeNivel(nivel) {
  const value = slug(nivel);
  if (value === "medio") return "medio";
  return value || "medio";
}

function inferirCategoria(evento) {
  const text = slug(evento);
  if (/chuva|vendaval|tempest|granizo|frente|onda|estiagem|seca|umidade/.test(text)) return "Met";
  if (/desliz|lama|solo|inund|alag|enxurr|eros|rocha/.test(text)) return "Geo";
  if (/incendio/.test(text)) return "Fire";
  if (/doenc|saude/.test(text)) return "Health";
  return "Safety";
}

function extrairMunicipio(texto) {
  const first = String(texto || "").trim().split(",")[0].trim();
  for (const pattern of [/^(.+?)\s*\/\s*([A-Z]{2})$/i, /^(.+?)\s*-\s*([A-Z]{2})$/i, /^(.+?)\s*\(([A-Z]{2})\)$/i]) {
    const match = first.match(pattern);
    if (match) return { city: match[1].trim(), uf: match[2].toUpperCase() };
  }
  return { city: "", uf: "" };
}

function iniciarTimerRefresh() {
  atualizarTextoCountdown();
  setInterval(() => {
    refreshSecondsRemaining = Math.max(0, refreshSecondsRemaining - 1);
    atualizarTextoCountdown();
    if (refreshSecondsRemaining === 0) refreshSecondsRemaining = Math.floor(AUTO_REFRESH_MS / 1000);
  }, 1000);
}

function atualizarTextoCountdown() {
  const min = String(Math.floor(refreshSecondsRemaining / 60)).padStart(2, "0");
  const sec = String(refreshSecondsRemaining % 60).padStart(2, "0");
  setText("refresh-countdown", `${min}:${sec}`);
}

function renderErroGeral() {
  ["ultimos-alertas", "mapa-uf", "severity-breakdown", "event-breakdown", "hourly-breakdown"].forEach((id) => {
    const element = byId(id);
    if (element) element.innerHTML = `<div class="empty-state">Não foi possível carregar os dados do painel.</div>`;
  });
}

function dataValida(value) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function maiorData(alerts) {
  return (alerts || []).reduce((max, alerta) => {
    const date = dataValida(alerta.sent || alerta.onset);
    return date && (!max || date > max) ? date : max;
  }, null);
}

function chaveHora(date) {
  return date.toLocaleString("sv-SE", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
  }).replace(" ", "T");
}

function formatarDataHora(value) {
  const date = dataValida(value);
  if (!date) return "--/--/---- --:--:--";
  return date.toLocaleString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatarHora(value) {
  const date = dataValida(value);
  if (!date) return "--:--";
  return date.toLocaleTimeString("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" });
}

function formatarData(value) {
  const date = dataValida(value);
  if (!date) return "--/--/----";
  return date.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatarExpiracao(alerta) {
  return `Expira: ${formatarExpiracaoValor(alerta)}`;
}

function formatarExpiracaoValor(alerta) {
  const date = dataValida(alerta.expires || alerta.expires_br);
  if (!date) return "--/-- --:--";
  return date.toLocaleString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatarJanelaDados(data) {
  const hours = numeroBruto(data?.window_hours) || 24;
  if (hours % 24 === 0) {
    const days = hours / 24;
    return days === 1 ? "Últimas 24h" : `Últimos ${days} dias`;
  }
  return `Últimas ${hours}h`;
}

function formatarJanelaComPreposicao(data) {
  const label = formatarJanelaDados(data).toLowerCase();
  return label.startsWith("últimos") ? `nos ${label}` : `nas ${label}`;
}

function abreviarEmissor(sender) {
  return String(sender || "Emissor não informado").replace(/^Defesa Civil Estadual d[aeo]\s+/i, "DC ");
}

function titulo(value) {
  return String(value || "").toLowerCase().replace(/(^|\s)\S/g, (part) => part.toUpperCase());
}

function truncar(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit - 3)}...` : text;
}

function numero(value) {
  return numeroBruto(value).toLocaleString("pt-BR");
}

function numeroBruto(value) {
  return Number(value) || 0;
}

function slug(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]));
}

function escAttr(value) {
  return esc(value);
}

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const element = byId(id);
  if (element) element.textContent = value ?? "--";
}
