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
    renderMapaMunicipal(data, alerts);
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
  const vigentes = alerts.filter(estaVigente).length || numeroBruto(data.cards?.vigentes);
  const total = alerts.length || numeroBruto(data.cards?.ultimas24h);
  const graves = (levels.Severo || 0) + (levels.Extremo || 0) || numeroBruto(data.cards?.alertasSeverosExtremos);

  setText("card-24h", numero(total));
  setText("card-vigentes", numero(vigentes));
  setText("card-autoridades", numero(graves));
  setText("card-tipos-evento", numero(contarMunicipios(alerts)));
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
        <div class="recent-emissor-loc">${esc(alerta.municipio_nome || alerta.location || "Espírito Santo")}</div>
      </div>
      <div class="recent-content">
        <div class="recent-evento">${esc(titulo(alerta.event))}</div>
        <div class="recent-desc">${esc(truncar(alerta.headline || alerta.description || alerta.areaDesc || "Sem descrição disponível.", 150))}</div>
      </div>
      <div class="recent-status">
        <div class="recent-tag ${classeNivel(alerta.nivel)}">${esc(alerta.nivel)}</div>
        <div class="recent-expira">${esc(formatarExpiracao(alerta))}</div>
      </div>
    </div>
  `).join("");
}

async function renderMapaMunicipal(data, alerts) {
  const container = byId("mapa-uf");
  if (!container) return;

  try {
    const url = data.geo?.municipios_geojson || "data/geojs-es.json";
    const response = await fetch(`${url}?_=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Falha ao carregar GeoJSON municipal: ${response.status}`);

    const geojson = await response.json();
    container.innerHTML = `
      <div class="map-inner">
        <div class="map-svg-wrap">${montarMapaMunicipalSvg(geojson, contarAlertasPorMunicipio(alerts))}</div>
      </div>
    `;
  } catch (error) {
    console.error("Erro ao renderizar mapa municipal:", error);
    container.innerHTML = `<div class="empty-state">Mapa municipal do ES indisponível.</div>`;
  }
}

function montarMapaMunicipalSvg(geojson, counts) {
  const features = geojson.features || [];
  const points = [];
  features.forEach((feature) => coletarPontos(feature.geometry, points));
  if (!points.length) return `<div class="empty-state">Malha municipal sem geometria.</div>`;

  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const width = 420;
  const height = 620;
  const pad = 8;
  const scale = Math.min((width - pad * 2) / (maxX - minX), (height - pad * 2) / (maxY - minY));
  const offsetX = (width - (maxX - minX) * scale) / 2;
  const offsetY = (height - (maxY - minY) * scale) / 2;
  const maxCount = Math.max(...Object.values(counts), 0);

  function project([lon, lat]) {
    return [(lon - minX) * scale + offsetX, (maxY - lat) * scale + offsetY];
  }

  const paths = features.map((feature) => {
    const props = feature.properties || {};
    const code = String(props.codigo_ibge || props.id || "");
    const name = props.nome || props.name || props.description || "Município";
    const key = code || slug(name);
    const count = Number(counts[key] || counts[slug(name)] || 0);
    return `
      <path class="municipio-shape" d="${geometryToPath(feature.geometry, project)}" fill="${corMunicipio(count, maxCount)}">
        <title>${esc(name)}: ${numero(count)} alerta(s)</title>
      </path>
    `;
  }).join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Mapa municipal do Espírito Santo">
      ${paths}
    </svg>
  `;
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

  return {
    ...alerta,
    senderName,
    senderNameShort: alerta.senderNameShort || abreviarEmissor(senderName),
    sent,
    uf: String(alerta.uf || alerta.uf_hint || locationInfo.uf || "ES").toUpperCase(),
    municipio_id: String(alerta.municipio_id || ""),
    municipio_nome: alerta.municipio_nome || locationInfo.city || "",
    event: alerta.event_short || alerta.event || alerta.evento || "Sem evento",
    nivel: normalizarNivel(alerta.nivel || alerta.severity || "Indefinido"),
    location: alerta.location || alerta.municipio_nome || alerta.areaDesc || "Espírito Santo",
    category: alerta.category || inferirCategoria(alerta.event || alerta.evento),
  };
}

function contarAlertasPorMunicipio(alerts) {
  const values = {};
  alerts.forEach((alerta) => {
    const key = alerta.municipio_id || slug(alerta.municipio_nome || alerta.location || "");
    if (key) values[key] = (values[key] || 0) + 1;
  });
  return values;
}

function contarMunicipios(alerts) {
  const values = new Set();
  alerts.forEach((alerta) => {
    const key = alerta.municipio_id || alerta.municipio_nome || "";
    if (key) values.add(key);
  });
  return values.size;
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

function coletarPontos(geometry, output) {
  if (!geometry) return;
  if (geometry.type === "Polygon") geometry.coordinates.flat(1).forEach((point) => output.push(point));
  if (geometry.type === "MultiPolygon") geometry.coordinates.flat(2).forEach((point) => output.push(point));
}

function geometryToPath(geometry, project) {
  if (!geometry) return "";
  if (geometry.type === "Polygon") return polygonToPath(geometry.coordinates, project);
  if (geometry.type === "MultiPolygon") return geometry.coordinates.map((polygon) => polygonToPath(polygon, project)).join("");
  return "";
}

function polygonToPath(coords, project) {
  return coords.map((ring) => ring.map((point, index) => {
    const [x, y] = project(point);
    return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join("") + "Z").join("");
}

function corMunicipio(count, maxCount) {
  if (!count || maxCount <= 0) return "#dfe5ef";
  const ratio = count / maxCount;
  if (ratio >= 0.8) return "#6c4ce6";
  if (ratio >= 0.6) return "#e23d2f";
  if (ratio >= 0.4) return "#ea8f1c";
  if (ratio >= 0.2) return "#2f9e59";
  return "#2c7ae8";
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
  const date = dataValida(alerta.expires || alerta.expires_br);
  if (!date) return "Expira: --/-- --:--";
  return `Expira: ${date.toLocaleString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
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
