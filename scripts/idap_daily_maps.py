#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Coleta alertas CAP do IDAP para o Espírito Santo e gera saídas do site.

Saídas:
- alertas_idap.geojson
- grafico_alertas_por_hora_24h.png
- alerts_feed.json, alerts_24h.json, historico_alertas.json, errors.json, resumo.json, resumo.md

Regras:
- Monitora apenas TARGET_SENDER_NAME.
- Mantém histórico local para preservar alertas além da janela curta do RSS.
- Deduplica pelo atom:id do RSS.
- Usa a malha municipal do Espírito Santo em site/data/geojs-es.json.
- Publica os polígonos em GeoJSON para renderização dinâmica no navegador.
"""

import json
import os
import re
import time
import unicodedata
import urllib.request
import urllib.error
import urllib.parse
import http.client
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.geometry.base import BaseGeometry


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}

DEFAULT_RSS_URL = "https://idapfile.mdr.gov.br/idap/api/rss/cap"
DEFAULT_UF_GEOJSON_PATH = "site/data/geojs-es.json"
DEFAULT_MUN_GEOJSON_PATH = DEFAULT_UF_GEOJSON_PATH
DEFAULT_OUT_DIR = "out"
DEFAULT_STATE_PATH = ".cache/state.json"
DEFAULT_HISTORY_PATH = ".cache/historico_alertas.json"
DEFAULT_ALERTS_GEOJSON_PATH = "site/data/alertas_idap.geojson"
DEFAULT_WINDOW_HOURS = 24
DEFAULT_RETENTION_HOURS = 72
DEFAULT_TARGET_SENDER_NAME = "Defesa Civil Estadual do Espírito Santo"

UF_TO_REGION = {"ES": "SE"}

NIVEL_COLORS = {
    "Extremo": "#6a0dad",
    "Severo":  "#d62728",
    "Alto":    "#ff7f0e",
    "Médio":   "#ffd92f",
    "Baixo":   "#2ca02c",
    "Indefinido": "#7f7f7f",
}

def calc_nivel(severity: str, urgency: str, certainty: str, response_type: str) -> str:
    s = (severity or "").strip()
    u = (urgency or "").strip()
    c = (certainty or "").strip()
    r = (response_type or "").strip()

    if s == "Extreme":
        if u == "Immediate" and c in {"Likely", "Observed"} and r in {"Evacuate", "Shelter", "Execute"}:
            return "Extremo"
        return "Severo"

    if s == "Severe":
        return "Alto"

    if s == "Moderate":
        return "Médio"

    if s == "Minor":
        return "Baixo"

    return "Indefinido"

def nivel_emoji(nivel: str) -> str:
    n = (nivel or "").strip()
    return {
        "Extremo": "ðŸŸ£",
        "Severo": "ðŸ”´",
        "Alto": "ðŸŸ ",
        "Médio": "ðŸŸ¡",
        "Baixo": "ðŸŸ¢",
        "Indefinido": "âšª",
    }.get(n, "âšª")


@dataclass
class AlertRecord:
    identifier: str
    entry_id: str
    sender: Optional[str]
    senderName: Optional[str]
    sent: Optional[str]
    status: Optional[str]
    msgType: Optional[str]
    category: Optional[str]
    event: Optional[str]
    responseType: Optional[str]
    urgency: Optional[str]
    severity: Optional[str]
    certainty: Optional[str]
    onset: Optional[str]
    expires: Optional[str]
    nivel: str
    headline: Optional[str]
    description: Optional[str]
    instruction: Optional[str]
    web: Optional[str]
    contact: Optional[str]
    channel_list: Optional[str]
    areaDesc: Optional[str]
    polygon_raw: Optional[str]
    polygon_points: int
    has_geocode: bool
    uf_hint: Optional[str]
    region: Optional[str]
    geometry_wkt: Optional[str]
    municipio_id: Optional[str] = None
    municipio_nome: Optional[str] = None
    municipio_slug: Optional[str] = None
    municipio_area_km2: Optional[float] = None
    microrregiao_nome: Optional[str] = None
    mesorregiao_nome: Optional[str] = None
    regiao_imediata_nome: Optional[str] = None
    regiao_intermediaria_nome: Optional[str] = None
    affected_municipios: Optional[List[Dict[str, Any]]] = None


def _now_sp() -> datetime:
    override = os.getenv("NOW_OVERRIDE")
    if override:
        txt = override.strip()
        try:
            if txt.endswith("Z"):
                txt = txt[:-1] + "+00:00"
            dt = datetime.fromisoformat(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone()
        except Exception:
            pass
    return datetime.now().astimezone()


_PT_MONTHS = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}


def _format_window_label(window_hours: int) -> str:
    if window_hours % 24 == 0:
        days = window_hours // 24
        if days == 1:
            return "últimas 24h"
        return f"últimos {days} dias"
    return f"últimas {window_hours}h"


def _format_period_title(window_hours: int = DEFAULT_WINDOW_HOURS) -> str:
    now_dt = _now_sp()
    return f"Alertas {_format_window_label(window_hours)} - Gerado em: {now_dt.day:02d} de {_PT_MONTHS[now_dt.month]} de {now_dt.year}"


def _parse_iso_any(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    txt = s.strip()
    if not txt:
        return None
    try:
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    except Exception:
        return None


def _safe_text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None:
        return None
    txt = elem.text
    if txt is None:
        return None
    txt = txt.strip()
    if "Ã" in txt or "Â" in txt:
        try:
            txt = txt.encode("latin-1").decode("utf-8")
        except Exception:
            pass
    return txt if txt != "" else None


def _first(elem: ET.Element, path: str, ns: Dict[str, str]) -> Optional[ET.Element]:
    try:
        return elem.find(path, ns)
    except Exception:
        return None


def _all(elem: ET.Element, path: str, ns: Dict[str, str]) -> List[ET.Element]:
    try:
        return elem.findall(path, ns) or []
    except Exception:
        return []


def _read_local_source(source: str) -> Optional[bytes]:
    text = (source or "").strip()
    if not text:
        return None

    if text.lower().startswith("file://"):
        parsed = urllib.parse.urlparse(text)
        local_path = urllib.request.url2pathname(parsed.path)
        if parsed.netloc:
            local_path = f"//{parsed.netloc}{local_path}"
        path = Path(local_path)
    else:
        path = Path(text)

    if path.exists() and path.is_file():
        return path.read_bytes()
    return None


def _read_url(url: str, timeout: int = 30, retries: int = 3, backoff_s: float = 1.2) -> bytes:
    local_data = _read_local_source(url)
    if local_data is not None:
        return local_data

    last_err: Optional[Exception] = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "IDAP-Daily-Maps/1.5 (+github-actions)", "Accept": "*/*"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except http.client.IncompleteRead as e:
            last_err = e
        except urllib.error.URLError as e:
            last_err = e
        except Exception as e:
            last_err = e
        time.sleep(backoff_s * (i + 1))
    raise last_err if last_err else RuntimeError("Falha ao baixar URL (erro desconhecido)")


def _normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip()
    if not s:
        return ""
    if "Ã" in s or "Â" in s:
        try:
            s = s.encode("latin-1").decode("utf-8")
        except Exception:
            pass
    s2 = unicodedata.normalize("NFKD", s)
    s2 = "".join([c for c in s2 if not unicodedata.combining(c)])
    return s2.upper()


def _slugify(s: Optional[str]) -> str:
    text = _normalize_text(s).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def _same_sender_name(value: Optional[str], target: str) -> bool:
    return _normalize_text(value) == _normalize_text(target)


def _parse_polygon_str(poly_str: str) -> Optional[BaseGeometry]:
    if not poly_str:
        return None
    poly_str = poly_str.strip()
    if not poly_str:
        return None
    pts: List[Tuple[float, float]] = []
    for token in poly_str.split():
        if "," not in token:
            continue
        a, b = token.split(",", 1)
        try:
            lat = float(a)
            lon = float(b)
        except ValueError:
            continue
        pts.append((lon, lat))
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    geom: BaseGeometry = Polygon(pts)
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty:
        return None
    return geom


def _geom_points_count(geom: Optional[BaseGeometry]) -> int:
    try:
        if geom is None or geom.is_empty:
            return 0
        if geom.geom_type == "Polygon":
            return len(geom.exterior.coords) if geom.exterior else 0
        if geom.geom_type == "MultiPolygon":
            best = 0
            mp: MultiPolygon = geom  # type: ignore
            for g in mp.geoms:
                if g.exterior:
                    best = max(best, len(g.exterior.coords))
            return best
        return 0
    except Exception:
        return 0


STATE_NAME_TO_UF = {
    "ESPIRITO SANTO": "ES",
}


def _guess_uf_from_text(text: Optional[str]) -> Optional[str]:
    txt = (text or "").strip().upper()
    if not txt:
        return None

    for pat in (r"/([A-Z]{2})\b", r"\(([A-Z]{2})\)", r"\b([A-Z]{2})\b"):
        m = re.search(pat, txt)
        if m and m.group(1) in UF_TO_REGION:
            return m.group(1)

    normalized = _normalize_text(txt)
    for state_name, uf in STATE_NAME_TO_UF.items():
        if state_name in normalized:
            return uf

    return None


def _guess_uf(area_desc: Optional[str], sender_name: Optional[str] = None) -> Optional[str]:
    return _guess_uf_from_text(area_desc) or _guess_uf_from_text(sender_name)


def _uf_to_region(uf: Optional[str]) -> Optional[str]:
    if not uf:
        return None
    return UF_TO_REGION.get(uf.strip().upper())


def _cap_get_parameter(info_elem: ET.Element, value_name: str) -> Optional[str]:
    for p in _all(info_elem, "cap:parameter", CAP_NS):
        vn = _safe_text(_first(p, "cap:valueName", CAP_NS))
        if vn and vn.strip().upper() == value_name.strip().upper():
            return _safe_text(_first(p, "cap:value", CAP_NS))
    return None


def _extract_cap_xml_from_entry(entry: ET.Element) -> Optional[ET.Element]:
    content = _first(entry, "atom:content", ATOM_NS)
    if content is None:
        return None
    for child in list(content):
        if child.tag.endswith("alert"):
            return child
    raw = content.text
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        root = ET.fromstring(raw)
        if root.tag.endswith("alert"):
            return root
    except Exception:
        pass
    raw2 = raw.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    try:
        root = ET.fromstring(raw2)
        if root.tag.endswith("alert"):
            return root
    except Exception:
        return None
    return None


def _parse_cap_from_entry(entry: ET.Element) -> Tuple[Optional[AlertRecord], Optional[str]]:
    try:
        cap_alert = _extract_cap_xml_from_entry(entry)
        if cap_alert is None:
            return None, "entry sem CAP <alert>"
        entry_id = _safe_text(_first(entry, "atom:id", ATOM_NS)) or "UNKNOWN"
        identifier = _safe_text(_first(cap_alert, "cap:identifier", CAP_NS)) or entry_id
        sender = _safe_text(_first(cap_alert, "cap:sender", CAP_NS))
        sent = _safe_text(_first(cap_alert, "cap:sent", CAP_NS))
        status = _safe_text(_first(cap_alert, "cap:status", CAP_NS))
        msgType = _safe_text(_first(cap_alert, "cap:msgType", CAP_NS))
        info = _first(cap_alert, "cap:info", CAP_NS)
        if info is None:
            infos = _all(cap_alert, "cap:info", CAP_NS)
            info = infos[0] if infos else None
        category = event = responseType = urgency = severity = certainty = onset = expires = None
        senderName = headline = description = instruction = web = contact = None
        channel_list = None
        areaDesc = None
        polygon_raw = None
        has_geocode = False
        geom: Optional[BaseGeometry] = None
        if info is not None:
            category = _safe_text(_first(info, "cap:category", CAP_NS))
            event = _safe_text(_first(info, "cap:event", CAP_NS))
            responseType = _safe_text(_first(info, "cap:responseType", CAP_NS))
            urgency = _safe_text(_first(info, "cap:urgency", CAP_NS))
            severity = _safe_text(_first(info, "cap:severity", CAP_NS))
            certainty = _safe_text(_first(info, "cap:certainty", CAP_NS))
            onset = _safe_text(_first(info, "cap:onset", CAP_NS))
            expires = _safe_text(_first(info, "cap:expires", CAP_NS))
            senderName = _safe_text(_first(info, "cap:senderName", CAP_NS))
            headline = _safe_text(_first(info, "cap:headline", CAP_NS))
            description = _safe_text(_first(info, "cap:description", CAP_NS))
            instruction = _safe_text(_first(info, "cap:instruction", CAP_NS))
            web = _safe_text(_first(info, "cap:web", CAP_NS))
            contact = _safe_text(_first(info, "cap:contact", CAP_NS))
            channel_list = _cap_get_parameter(info, "CHANNEL-LIST")
            area = _first(info, "cap:area", CAP_NS)
            if area is not None:
                areaDesc = _safe_text(_first(area, "cap:areaDesc", CAP_NS))
                polygon_raw = _safe_text(_first(area, "cap:polygon", CAP_NS))
                geocodes = _all(area, "cap:geocode", CAP_NS)
                has_geocode = len(geocodes) > 0
                if polygon_raw:
                    geom = _parse_polygon_str(polygon_raw)
        uf_hint = _guess_uf(areaDesc, senderName)
        region = _uf_to_region(uf_hint)
        nivel = calc_nivel(severity or "", urgency or "", certainty or "", responseType or "")
        rec = AlertRecord(
            identifier=identifier,
            entry_id=entry_id,
            sender=sender,
            senderName=senderName,
            sent=sent,
            status=status,
            msgType=msgType,
            category=category,
            event=event,
            responseType=responseType,
            urgency=urgency,
            severity=severity,
            certainty=certainty,
            onset=onset,
            expires=expires,
            nivel=nivel,
            headline=headline,
            description=description,
            instruction=instruction,
            web=web,
            contact=contact,
            channel_list=channel_list,
            areaDesc=areaDesc,
            polygon_raw=polygon_raw,
            polygon_points=_geom_points_count(geom),
            has_geocode=has_geocode,
            uf_hint=uf_hint,
            region=region,
            geometry_wkt=geom.wkt if geom is not None else None,
        )
        return rec, None
    except Exception as e:
        return None, f"erro parse CAP: {e}"


def _load_uf_gdf(path: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        try:
            gdf = gdf.to_crs("EPSG:4326")
        except Exception:
            pass
    return gdf


def _load_municipios_gdf(path: str) -> gpd.GeoDataFrame:
    gdf = _load_uf_gdf(path)
    expected = 78
    if len(gdf) != expected:
        print(f"[WARN] Malha municipal do ES deveria ter {expected} municipios, mas tem {len(gdf)}")
    return gdf


def _municipio_props(row: Any) -> Dict[str, Any]:
    nome = row.get("nome") or row.get("name") or row.get("NM_MUN") or row.get("description") or ""
    return {
        "municipio_id": str(row.get("codigo_ibge") or row.get("id") or row.get("CD_MUN") or ""),
        "municipio_nome": nome,
        "municipio_slug": row.get("slug") or _slugify(nome),
        "municipio_area_km2": row.get("area_km2"),
        "microrregiao_nome": row.get("microrregiao_nome") or "",
        "mesorregiao_nome": row.get("mesorregiao_nome") or "",
        "regiao_imediata_nome": row.get("regiao_imediata_nome") or "",
        "regiao_intermediaria_nome": row.get("regiao_intermediaria_nome") or "",
    }


def _match_municipio_by_text(alert: AlertRecord, municipios_gdf: gpd.GeoDataFrame) -> Optional[Dict[str, Any]]:
    haystack = " ".join([alert.areaDesc or "", alert.headline or "", alert.description or ""])
    normalized = _normalize_text(haystack)
    if not normalized:
        return None

    best = None
    best_len = 0
    for _, row in municipios_gdf.iterrows():
        name = str(row.get("nome") or row.get("name") or row.get("NM_MUN") or row.get("description") or "")
        n = _normalize_text(name)
        if n and re.search(rf"(^|[^A-Z0-9]){re.escape(n)}([^A-Z0-9]|$)", normalized):
            if len(n) > best_len:
                best = _municipio_props(row)
                best_len = len(n)

    return best


def _match_municipios_by_geometry(alert: AlertRecord, municipios_gdf: gpd.GeoDataFrame) -> List[Dict[str, Any]]:
    if not alert.geometry_wkt:
        return []

    try:
        geom = gpd.GeoSeries.from_wkt([alert.geometry_wkt], crs="EPSG:4326").iloc[0]
    except Exception:
        return []

    try:
        candidates = municipios_gdf[municipios_gdf.intersects(geom)].copy()
    except Exception:
        return []

    if candidates.empty:
        return []

    try:
        intersections = gpd.GeoSeries(
            candidates.geometry.intersection(geom),
            index=candidates.index,
            crs=municipios_gdf.crs or "EPSG:4326",
        )
        areas = intersections.to_crs("EPSG:31984").area.sort_values(ascending=False)
        matched: List[Dict[str, Any]] = []
        for idx, area_m2 in areas.items():
            if float(area_m2) <= 0:
                continue
            props = _municipio_props(candidates.loc[idx])
            props["intersection_area_m2"] = round(float(area_m2), 2)
            matched.append(props)
        return matched
    except Exception:
        return [_municipio_props(row) for _, row in candidates.iterrows()]


def _match_municipio_by_geometry(alert: AlertRecord, municipios_gdf: gpd.GeoDataFrame) -> Optional[Dict[str, Any]]:
    matched = _match_municipios_by_geometry(alert, municipios_gdf)
    return matched[0] if matched else None


def _enrich_alerts_with_municipios(alerts: List[AlertRecord], municipios_gdf: gpd.GeoDataFrame) -> List[AlertRecord]:
    enriched: List[AlertRecord] = []
    for alert in alerts:
        affected = _match_municipios_by_geometry(alert, municipios_gdf)
        if not affected:
            props_by_text = _match_municipio_by_text(alert, municipios_gdf)
            affected = [props_by_text] if props_by_text else []

        if affected:
            props = affected[0]
            for key, value in props.items():
                setattr(alert, key, value)
            alert.affected_municipios = affected
            alert.uf_hint = "ES"
            alert.region = "SE"
        enriched.append(alert)
    return enriched


def _alerts_to_gdf(alerts: List[AlertRecord]) -> gpd.GeoDataFrame:
    geoms = []
    rows = []
    for a in alerts:
        if not a.geometry_wkt:
            continue
        try:
            geom = gpd.GeoSeries.from_wkt([a.geometry_wkt], crs="EPSG:4326").iloc[0]
        except Exception:
            continue
        geoms.append(geom)
        rows.append(a)
    if not rows:
        return gpd.GeoDataFrame(columns=["identifier"], geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame([asdict(r) for r in rows], geometry=geoms, crs="EPSG:4326")


def _count_by(alerts: List[AlertRecord], key_fn) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for a in alerts:
        k = key_fn(a) or "N/A"
        d[k] = d.get(k, 0) + 1
    return dict(sorted(d.items(), key=lambda x: (-x[1], x[0])))


def _make_summary(alerts: List[AlertRecord]) -> Dict[str, Any]:
    return {
        "total_alerts": len(alerts),
        "by_nivel": _count_by(alerts, lambda a: a.nivel),
        "by_channel_list": _count_by(alerts, lambda a: a.channel_list),
        "by_region": _count_by(alerts, lambda a: a.region),
        "by_municipio": _count_affected_municipios(alerts),
    }


def _count_affected_municipios(alerts: List[AlertRecord]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for alert in alerts:
        municipios = alert.affected_municipios or []
        if not municipios and alert.municipio_nome:
            municipios = [{"municipio_nome": alert.municipio_nome, "municipio_id": alert.municipio_id}]

        seen_in_alert = set()
        for municipio in municipios:
            nome = str(municipio.get("municipio_nome") or municipio.get("nome") or "").strip()
            key = nome or str(municipio.get("municipio_id") or "").strip() or "N/A"
            if key in seen_in_alert:
                continue
            seen_in_alert.add(key)
            counts[key] = counts.get(key, 0) + 1

    return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))


def _ensure_dirs(*paths: str) -> None:
    for p in paths:
        os.makedirs(p, exist_ok=True)


def _load_json_file(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json_file(path: str, data: Any) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_state(path: str) -> Dict[str, Any]:
    return _load_json_file(path, {})


def _save_state(path: str, state: Dict[str, Any]) -> None:
    _save_json_file(path, state)


def _load_history(path: str) -> List[AlertRecord]:
    raw = _load_json_file(path, [])
    alerts: List[AlertRecord] = []
    if not isinstance(raw, list):
        return alerts
    for item in raw:
        try:
            if not isinstance(item, dict):
                continue
            if "entry_id" not in item:
                item["entry_id"] = item.get("identifier", "UNKNOWN")
            alerts.append(AlertRecord(**item))
        except Exception:
            continue
    return alerts


def _save_history(path: str, alerts: List[AlertRecord]) -> None:
    _save_json_file(path, [asdict(a) for a in alerts])


def _merge_history(existing: List[AlertRecord], new_alerts: List[AlertRecord]) -> Tuple[List[AlertRecord], int]:
    merged: Dict[str, AlertRecord] = {}
    for a in existing:
        key = (a.entry_id or a.identifier or "").strip()
        if key:
            merged[key] = a
    added = 0
    for a in new_alerts:
        key = (a.entry_id or a.identifier or "").strip()
        if not key:
            continue
        if key not in merged:
            added += 1
        merged[key] = a
    def _sort_key(a: AlertRecord) -> datetime:
        return _parse_iso_any(a.onset) or _parse_iso_any(a.sent) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    items = list(merged.values())
    items.sort(key=_sort_key)
    return items, added


def _filter_recent_history(alerts: List[AlertRecord], retention_hours: int, ref_now: datetime) -> List[AlertRecord]:
    cutoff = ref_now - timedelta(hours=retention_hours)
    kept: List[AlertRecord] = []
    for a in alerts:
        ref_dt = _parse_iso_any(a.onset) or _parse_iso_any(a.sent)
        if ref_dt is None:
            continue
        if ref_dt >= cutoff:
            kept.append(a)
    return kept


def _filter_window(alerts: List[AlertRecord], window_hours: int, ref_now: datetime) -> List[AlertRecord]:
    cutoff = ref_now - timedelta(hours=window_hours)
    selected: List[AlertRecord] = []
    for a in alerts:
        ref_dt = _parse_iso_any(a.onset) or _parse_iso_any(a.sent)
        if ref_dt is None:
            continue
        if cutoff <= ref_dt <= ref_now:
            selected.append(a)
    return selected


def _write_resumo_md(path: str, resumo: Dict[str, Any], window_hours: int = DEFAULT_WINDOW_HOURS) -> None:
    lines = ["# Quadro geral", "", f"Total de alertas ({_format_window_label(window_hours)}): **{resumo.get('total_alerts', 0)}**", ""]
    def _block(title: str, d: Dict[str, int], emoji: bool = False):
        lines.append(f"## {title}")
        lines.append("")
        for k, v in d.items():
            lines.append(f"- {nivel_emoji(k)} {k}: {v}" if emoji else f"- {k}: {v}")
        lines.append("")
    _block("Nível (calculado)", resumo.get("by_nivel", {}), emoji=True)
    _block("Tipo (CHANNEL-LIST)", resumo.get("by_channel_list", {}), emoji=False)
    _block("Alertas por regiões do Brasil", resumo.get("by_region", {}), emoji=False)
    _block("Alertas por município do Espírito Santo", resumo.get("by_municipio", {}), emoji=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _nivel_color(n: str) -> str:
    return NIVEL_COLORS.get((n or "").strip(), NIVEL_COLORS["Indefinido"])


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _format_dt_label(value: Optional[str]) -> Optional[str]:
    dt = _parse_iso_any(value)
    if dt is None:
        return None
    return dt.strftime("%d/%m/%Y %H:%M")


def _alert_to_feature(alert: AlertRecord) -> Optional[Dict[str, Any]]:
    if not alert.geometry_wkt:
        return None
    try:
        geom = gpd.GeoSeries.from_wkt([alert.geometry_wkt], crs="EPSG:4326").iloc[0]
    except Exception:
        return None

    properties = {
        key: _serialize_value(value)
        for key, value in asdict(alert).items()
        if key != "geometry_wkt"
    }
    properties["color"] = _nivel_color(alert.nivel)
    properties["sent_label"] = _format_dt_label(alert.sent)
    properties["onset_label"] = _format_dt_label(alert.onset)
    properties["expires_label"] = _format_dt_label(alert.expires)

    return {
        "type": "Feature",
        "properties": properties,
        "geometry": mapping(geom),
    }


def _write_alerts_geojson(path: str, alerts: List[AlertRecord]) -> int:
    features: List[Dict[str, Any]] = []
    for alert in alerts:
        feature = _alert_to_feature(alert)
        if feature is not None:
            features.append(feature)

    payload = {
        "type": "FeatureCollection",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_alerts": len(alerts),
        "features": features,
    }
    _save_json_file(path, payload)
    return len(features)


def _plot_alerts_per_hour(alerts: List[AlertRecord], out_path: str, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hourly_counts: Dict[datetime, int] = {}
    for a in alerts:
        dt = _parse_iso_any(a.onset)
        if dt is None:
            continue
        bucket = dt.replace(minute=0, second=0, microsecond=0)
        hourly_counts[bucket] = hourly_counts.get(bucket, 0) + 1

    if hourly_counts:
        buckets = sorted(hourly_counts.keys())
        start = buckets[0]
        end = buckets[-1]
    else:
        end = _now_sp().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=23)

    full_buckets: List[datetime] = []
    cur = start
    while cur <= end:
        full_buckets.append(cur)
        cur = cur + timedelta(hours=1)

    values = [hourly_counts.get(b, 0) for b in full_buckets]
    labels = [b.strftime('%d/%m - %H:%M') for b in full_buckets]

    fig = plt.figure(figsize=(14, 5), dpi=200)
    ax = plt.gca()
    ax.bar(range(len(full_buckets)), values)
    ax.set_title(title, fontsize=12)
    ax.set_ylabel('Quantidade de alertas')
    ax.set_xlabel('Hora de emissão (onset)')
    ax.set_xticks(range(len(full_buckets)))
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.grid(True, axis='y', alpha=0.3)
    if not hourly_counts:
        ax.text(
            0.5,
            0.55,
            "Nenhum alerta estadual do ES no periodo",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=13,
            color="#334155",
        )
        ax.set_ylim(0, 1)
    plt.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main() -> int:
    rss_url = os.getenv("RSS_URL", DEFAULT_RSS_URL)
    uf_geojson_path = os.getenv("UF_GEOJSON_PATH", DEFAULT_UF_GEOJSON_PATH)
    mun_geojson_path = os.getenv("MUN_GEOJSON_PATH", uf_geojson_path or DEFAULT_MUN_GEOJSON_PATH)
    out_dir = os.getenv("OUT_DIR", DEFAULT_OUT_DIR)
    state_path = os.getenv("STATE_PATH", DEFAULT_STATE_PATH)
    history_path = os.getenv("HISTORY_PATH", DEFAULT_HISTORY_PATH)
    alerts_geojson_path = os.getenv("ALERTS_GEOJSON_PATH", DEFAULT_ALERTS_GEOJSON_PATH)
    window_hours = int(os.getenv("WINDOW_HOURS", str(DEFAULT_WINDOW_HOURS)))
    retention_hours = int(os.getenv("RETENTION_HOURS", str(DEFAULT_RETENTION_HOURS)))
    target_sender_name = os.getenv("TARGET_SENDER_NAME", DEFAULT_TARGET_SENDER_NAME).strip()

    print(f"[INFO] RSS_URL={rss_url}")
    print(f"[INFO] UF_GEOJSON_PATH={uf_geojson_path}")
    print(f"[INFO] MUN_GEOJSON_PATH={mun_geojson_path}")
    print(f"[INFO] OUT_DIR={out_dir}")
    print(f"[INFO] HISTORY_PATH={history_path}")
    print(f"[INFO] ALERTS_GEOJSON_PATH={alerts_geojson_path}")
    print(f"[INFO] WINDOW_HOURS={window_hours}")
    print(f"[INFO] RETENTION_HOURS={retention_hours}")
    print(f"[INFO] TARGET_SENDER_NAME={target_sender_name}")

    run_ts = _now_sp().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(out_dir, f"run_{run_ts}")
    print(f"[INFO] RUN_DIR={run_dir}")
    print(f"[INFO] STATE_PATH={state_path}")

    _ensure_dirs(".cache", out_dir, run_dir)

    state = _load_state(state_path)

    try:
        rss_bytes = _read_url(rss_url, timeout=45, retries=4)
    except Exception as e:
        print(f"[ERROR] Falha ao baixar RSS: {e}")
        return 2

    try:
        root = ET.fromstring(rss_bytes)
    except Exception as e:
        print(f"[ERROR] RSS inválido (XML): {e}")
        return 3

    entries = _all(root, "atom:entry", ATOM_NS)
    print(f"[INFO] Entradas no RSS (lidas): {len(entries)}")

    feed_alerts: List[AlertRecord] = []
    errors: List[Dict[str, Any]] = []
    ignored_by_sender = 0
    for entry in entries:
        a, err = _parse_cap_from_entry(entry)
        if a is None:
            errors.append({"error": err or "desconhecido"})
            continue
        if not _same_sender_name(a.senderName, target_sender_name):
            ignored_by_sender += 1
            continue
        feed_alerts.append(a)

    print(f"[INFO] CAPs parseados do feed: {len(feed_alerts)} | ignorados por senderName: {ignored_by_sender} | erros: {len(errors)}")

    try:
        municipios_gdf = _load_municipios_gdf(mun_geojson_path)
        feed_alerts = _enrich_alerts_with_municipios(feed_alerts, municipios_gdf)
    except Exception as e:
        print(f"[ERROR] Falha ao ler/enriquecer municipios do ES: {e}")
        return 4

    history_before = [
        a for a in _load_history(history_path)
        if _same_sender_name(a.senderName, target_sender_name)
    ]
    history_merged, added_count = _merge_history(history_before, feed_alerts)
    history_merged = _enrich_alerts_with_municipios(history_merged, municipios_gdf)
    history_kept = _filter_recent_history(history_merged, retention_hours=retention_hours, ref_now=_now_sp())
    alerts = _filter_window(history_kept, window_hours=window_hours, ref_now=_now_sp())

    print(f"[INFO] Histórico anterior: {len(history_before)}")
    print(f"[INFO] Alertas novos inseridos no histórico: {added_count}")
    print(f"[INFO] Histórico após limpeza: {len(history_kept)}")
    print(f"[INFO] Alertas considerados nas últimas {window_hours}h: {len(alerts)}")

    _save_history(history_path, history_kept)
    _save_history(os.path.join(run_dir, "historico_alertas.json"), history_kept)

    with open(os.path.join(run_dir, "alerts_feed.json"), "w", encoding="utf-8") as f:
        json.dump([asdict(a) for a in feed_alerts], f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "alerts_24h.json"), "w", encoding="utf-8") as f:
        json.dump([asdict(a) for a in alerts], f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "errors.json"), "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)

    resumo = _make_summary(alerts)
    
    with open(os.path.join(run_dir, "resumo.json"), "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)
    _write_resumo_md(os.path.join(run_dir, "resumo.md"), resumo, window_hours)

    run_geojson_path = os.path.join(run_dir, "alertas_idap.geojson")
    feature_count = _write_alerts_geojson(run_geojson_path, alerts)
    _write_alerts_geojson(alerts_geojson_path, alerts)
    print(f"[INFO] GeoJSON gerado: {run_geojson_path} | feicoes: {feature_count}")
    print(f"[INFO] GeoJSON atualizado no site: {alerts_geojson_path}")

    graf_hora = os.path.join(run_dir, "grafico_alertas_por_hora_24h.png")
    
    try:
        _plot_alerts_per_hour(alerts, graf_hora, f"Alertas emitidos por hora nas {_format_window_label(window_hours)} - Defesa Civil Estadual do ES")
        if os.path.exists(graf_hora):
            print(f"[INFO] Gráfico gerado: {graf_hora}")
        else:
            graf_hora = ""
            print("[WARN] Gráfico por hora não gerado: nenhum alerta válido no período")
    except Exception as e:
        graf_hora = ""
        print(f"[WARN] Falha ao gerar gráfico por hora: {e}")


    state["last_run_ts"] = run_ts
    state["last_run_iso"] = datetime.now(timezone.utc).isoformat()
    state["last_counts"] = {
        "entries": len(entries),
        "feed_alerts": len(feed_alerts),
        "window_alerts": len(alerts),
        "geojson_features": feature_count,
        "history_alerts": len(history_kept),
        "errors": len(errors),
        "ignored_by_sender": ignored_by_sender,
    }
    state["history_path"] = history_path
    state["alerts_geojson_path"] = alerts_geojson_path
    state["window_hours"] = window_hours
    state["retention_hours"] = retention_hours
    _save_state(state_path, state)

    print("[INFO] Finalizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
