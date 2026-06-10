#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_dashboard.py

Gera o arquivo site/dashboard_data.json para o dashboard principal.

Entrada principal:
  .cache/historico_alertas.json

Preserva os campos extraídos pelo idap_daily_maps.py e acrescenta dados
derivados para o dashboard: status de vigência, duração, tempo desde emissão,
município, evento curto e agregações.
"""

import json
import os
import re
import shutil
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo


DEFAULT_HISTORY_PATH = ".cache/historico_alertas.json"
DEFAULT_SITE_DIR = "site"
DEFAULT_WINDOW_HOURS = 24
DEFAULT_GEOJSON_SOURCE = "site/data/geojs-es.json"
DEFAULT_GEOJSON_TARGET = "site/data/geojs-es.json"
DEFAULT_MUNICIPALITIES_SOURCE = DEFAULT_GEOJSON_SOURCE
DEFAULT_TARGET_SENDER_NAME = "Defesa Civil Estadual do Espírito Santo"

TZ_BRASILIA = ZoneInfo("America/Sao_Paulo")

NIVEL_ORDER = ["Baixo", "Médio", "Alto", "Severo", "Extremo", "Indefinido"]
STATUS_ORDER = ["vigente", "futuro", "expirado", "sem_validade"]

UF_TO_REGION = {"ES": "SE"}
STATE_NAME_TO_UF = {"ESPIRITO SANTO": "ES"}


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    txt = str(value).strip()
    if not txt:
        return None

    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ_BRASILIA)
    except Exception:
        return None


def normalize_text(value: Optional[str]) -> str:
    txt = (value or "").strip()
    if not txt:
        return ""

    if "Ã" in txt or "Â" in txt:
        try:
            txt = txt.encode("latin-1").decode("utf-8")
        except Exception:
            pass

    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return txt.upper()


def same_sender_name(value: Optional[str], target: str) -> bool:
    return normalize_text(value) == normalize_text(target)


def short_event(value: Optional[str]) -> str:
    txt = (value or "").strip()
    if not txt:
        return "Não informado"

    if " - " in txt:
        txt = txt.split(" - ")[-1].strip()

    replacements = {
        "TEMPESTADE LOCAL/CONVECTIVA": "TEMPESTADE",
        "CORRIDA DE MASSA/SOLO/LAMA": "SOLO/LAMA",
        "CORRIDA DE MASSA/ROCHAS/DETRITOS": "ROCHAS/DETRITOS",
        "FRENTES FRIAS OU ZONAS DE CONVERGÊNCIA": "FRENTES FRIAS/ZONAS DE CONVERGÊNCIA",
    }

    for old, new in replacements.items():
        txt = txt.replace(old, new)

    return txt.title()


def short_emitter(value: Optional[str], max_len: int = 32) -> str:
    txt = (value or "Emissor não informado").strip()

    patterns = [
        r"^Defesa Civil Estadual de\s+(.+)$",
        r"^Defesa Civil Estadual do\s+(.+)$",
        r"^Defesa Civil Estadual da\s+(.+)$",
    ]

    for pat in patterns:
        m = re.match(pat, txt, flags=re.IGNORECASE)
        if m:
            out = f"DC {m.group(1).strip()}"
            return out if len(out) <= max_len else out[:max_len - 1].rstrip() + "â€¦"

    return txt if len(txt) <= max_len else txt[:max_len - 1].rstrip() + "â€¦"


def guess_uf_from_text(value: Optional[str]) -> str:
    txt = (value or "").strip().upper()
    if not txt:
        return ""

    patterns = [
        r"/([A-Z]{2})\b",
        r"-([A-Z]{2})\b",
        r"\(([A-Z]{2})\)",
        r"\b([A-Z]{2})\b$",
    ]

    for pat in patterns:
        m = re.search(pat, txt)
        if m and m.group(1) in UF_TO_REGION:
            return m.group(1)

    n = normalize_text(txt)
    for state_name, uf in sorted(STATE_NAME_TO_UF.items(), key=lambda x: -len(x[0])):
        if normalize_text(state_name) in n:
            return uf

    return ""


def derive_uf(alert: Dict[str, Any]) -> str:
    return (
        (alert.get("uf_hint") or "").strip().upper()
        or guess_uf_from_text(alert.get("areaDesc"))
        or guess_uf_from_text(alert.get("senderName"))
    )


def derive_location(alert: Dict[str, Any]) -> str:
    area = (alert.get("areaDesc") or "").strip()
    uf = derive_uf(alert)

    if area and len(area) <= 80:
        return area

    sender = (alert.get("senderName") or "").strip()
    if sender and len(sender) <= 80:
        return sender

    return uf or "Não informado"


def classify_status(now_dt: datetime, onset_dt: Optional[datetime], expires_dt: Optional[datetime]) -> str:
    if onset_dt and onset_dt > now_dt:
        return "futuro"

    if expires_dt:
        return "vigente" if expires_dt >= now_dt else "expirado"

    return "sem_validade"


def duration_minutes(onset_dt: Optional[datetime], expires_dt: Optional[datetime]) -> Optional[int]:
    if not onset_dt or not expires_dt:
        return None

    minutes = int((expires_dt - onset_dt).total_seconds() // 60)
    return minutes if minutes >= 0 else None


def time_since_minutes(now_dt: datetime, onset_dt: Optional[datetime]) -> Optional[int]:
    if not onset_dt:
        return None

    minutes = int((now_dt - onset_dt).total_seconds() // 60)
    return minutes if minutes >= 0 else None


def duration_bucket(minutes: Optional[int]) -> str:
    if minutes is None:
        return "Sem validade"

    h = minutes / 60

    if h <= 2:
        return "Até 2h"
    if h <= 6:
        return "2h a 6h"
    if h <= 12:
        return "6h a 12h"
    if h <= 24:
        return "12h a 24h"

    return "Mais de 24h"


def time_since_bucket(minutes: Optional[int]) -> str:
    if minutes is None:
        return "Sem data"

    h = minutes / 60

    if h <= 1:
        return "Até 1h"
    if h <= 3:
        return "1h a 3h"
    if h <= 6:
        return "3h a 6h"
    if h <= 12:
        return "6h a 12h"

    return "Mais de 12h"


def category_label(value: Optional[str]) -> str:
    txt = (value or "").strip()
    return txt if txt else "Sem categoria"


def event_category_fallback(event: Optional[str]) -> str:
    n = normalize_text(event)

    if any(k in n for k in ["CHUVA", "VENDAVAL", "TEMPESTADE", "GRANIZO", "FRENTE", "ONDA", "ESTIAGEM", "SECA", "UMIDADE"]):
        return "Met"

    if any(k in n for k in ["DESLIZ", "SOLO", "LAMA", "INUND", "ALAG", "ENXURR", "EROS", "ROCHA"]):
        return "Geo"

    if "INCENDIO" in n or "INCÊNDIO" in n:
        return "Fire"

    if "DOENC" in n or "SAUDE" in n or "SAÚDE" in n:
        return "Health"

    return "Safety"


def filter_window(alerts: List[Dict[str, Any]], window_hours: int, now_dt: datetime) -> List[Dict[str, Any]]:
    cutoff = now_dt.timestamp() - window_hours * 3600
    selected = []

    for a in alerts:
        ref_dt = parse_iso(a.get("onset") or a.get("sent"))
        if not ref_dt:
            continue
        if cutoff <= ref_dt.timestamp() <= now_dt.timestamp():
            selected.append(a)

    return selected


def make_latest_item(item: Dict[str, Any]) -> Dict[str, Any]:
    onset_dt = item.get("_onset_dt")

    return {
        "time": onset_dt.strftime("%H:%M") if onset_dt else "--:--",
        "date": onset_dt.strftime("%d/%m/%Y") if onset_dt else "--/--/----",
        "senderName": item.get("senderName") or "Emissor não informado",
        "senderNameShort": short_emitter(item.get("senderName"), 28),
        "event": item.get("event_short") or short_event(item.get("event")),
        "nivel": item.get("nivel") or "Indefinido",
        "location": item.get("location") or derive_location(item),
        "uf": item.get("uf") or "",
        "headline": item.get("headline") or item.get("description") or "",
        "status": item.get("status_vigencia") or "sem_validade",

        # Campos extras úteis no front.
        "identifier": item.get("identifier") or "",
        "entry_id": item.get("entry_id") or "",
        "sent": item.get("sent"),
        "onset": item.get("onset"),
        "expires": item.get("expires"),
        "category": item.get("category"),
        "severity": item.get("severity"),
        "urgency": item.get("urgency"),
        "certainty": item.get("certainty"),
        "responseType": item.get("responseType"),
        "channel_list": item.get("channel_list"),
        "municipio_id": item.get("municipio_id") or "",
        "municipio_nome": item.get("municipio_nome") or "",
        "affected_municipios": item.get("affected_municipios") or [],
        "affected_municipio_ids": item.get("affected_municipio_ids") or [],
        "affected_municipio_names": item.get("affected_municipio_names") or [],
    }



def slugify(value: Optional[str]) -> str:
    txt = (value or "").strip().lower()
    if not txt:
        return ""

    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = re.sub(r"[^a-z0-9]+", "-", txt)
    return re.sub(r"-+", "-", txt).strip("-")


def load_es_municipalities(path: Path) -> list[dict[str, Any]]:
    data = load_json(path, {})
    features = data.get("features") if isinstance(data, dict) else []
    municipalities: list[dict[str, Any]] = []

    for feature in features or []:
        props = feature.get("properties") or {}
        code = str(props.get("codigo_ibge") or props.get("id") or props.get("CD_MUN") or "")
        name = props.get("nome") or props.get("name") or props.get("NM_MUN") or props.get("description") or ""
        if not code or not name:
            continue

        municipalities.append({
            "id": code,
            "codigo_ibge": code,
            "nome": name,
            "slug": props.get("slug") or slugify(name),
            "uf": "ES",
            "area_km2": props.get("area_km2"),
            "populacao": props.get("populacao"),
            "microrregiao_nome": props.get("microrregiao_nome") or "",
            "mesorregiao_nome": props.get("mesorregiao_nome") or "",
            "regiao_imediata_nome": props.get("regiao_imediata_nome") or "",
            "regiao_intermediaria_nome": props.get("regiao_intermediaria_nome") or "",
        })

    municipalities.sort(key=lambda item: item["nome"])
    return municipalities


def match_municipality_from_text(alert: Dict[str, Any], municipalities: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    explicit_id = str(alert.get("municipio_id") or "").strip()
    if explicit_id:
        for municipality in municipalities:
            if municipality["codigo_ibge"] == explicit_id:
                return municipality

    haystack = " ".join([
        str(alert.get("municipio_nome") or ""),
        str(alert.get("location") or ""),
        str(alert.get("areaDesc") or ""),
        str(alert.get("headline") or ""),
        str(alert.get("description") or ""),
    ])
    normalized = normalize_text(haystack)
    if not normalized:
        return None

    best = None
    best_len = 0
    for municipality in municipalities:
        name = normalize_text(municipality["nome"])
        if name and re.search(rf"(^|[^A-Z0-9]){re.escape(name)}([^A-Z0-9]|$)", normalized):
            if len(name) > best_len:
                best = municipality
                best_len = len(name)

    return best


def apply_municipality_metadata(alert: Dict[str, Any], municipalities: list[dict[str, Any]]) -> Dict[str, Any]:
    municipality = match_municipality_from_text(alert, municipalities)
    if not municipality:
        return alert

    item = dict(alert)
    item.update({
        "municipio_id": municipality["codigo_ibge"],
        "municipio_nome": municipality["nome"],
        "municipio_slug": municipality["slug"],
        "municipio_area_km2": municipality.get("area_km2"),
        "microrregiao_nome": municipality.get("microrregiao_nome"),
        "mesorregiao_nome": municipality.get("mesorregiao_nome"),
        "regiao_imediata_nome": municipality.get("regiao_imediata_nome"),
        "regiao_intermediaria_nome": municipality.get("regiao_intermediaria_nome"),
    })
    return item


def normalize_affected_municipalities(alert: Dict[str, Any]) -> list[dict[str, Any]]:
    raw = alert.get("affected_municipios")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = str(item.get("municipio_id") or item.get("codigo_ibge") or item.get("id") or "").strip()
            name = str(item.get("municipio_nome") or item.get("nome") or item.get("name") or "").strip()
            key = code or slugify(name)
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append({
                "municipio_id": code,
                "municipio_nome": name,
                "municipio_slug": item.get("municipio_slug") or item.get("slug") or slugify(name),
                "intersection_area_m2": item.get("intersection_area_m2"),
            })

    if not normalized:
        code = str(alert.get("municipio_id") or "").strip()
        name = str(alert.get("municipio_nome") or "").strip()
        key = code or slugify(name)
        if key:
            normalized.append({
                "municipio_id": code,
                "municipio_nome": name,
                "municipio_slug": alert.get("municipio_slug") or slugify(name),
                "intersection_area_m2": None,
            })

    return normalized


def count_affected_municipalities(alerts: List[Dict[str, Any]]) -> tuple[Counter, set[str]]:
    counter: Counter = Counter()
    unique: set[str] = set()

    for alert in alerts:
        seen_in_alert: set[str] = set()
        for municipio in normalize_affected_municipalities(alert):
            code = str(municipio.get("municipio_id") or "").strip()
            name = str(municipio.get("municipio_nome") or "").strip()
            key = code or slugify(name)
            label = name or code or "Não identificado"
            if not key or key in seen_in_alert:
                continue
            seen_in_alert.add(key)
            unique.add(key)
            counter[label] += 1

    return counter, unique


def build_dashboard(history_path: Path, window_hours: int, municipalities_path: Path, target_sender_name: str) -> Dict[str, Any]:
    now_dt = parse_iso(os.getenv("NOW_OVERRIDE")) or datetime.now(TZ_BRASILIA)
    municipalities = load_es_municipalities(municipalities_path)

    raw_history = load_json(history_path, [])
    if not isinstance(raw_history, list):
        raw_history = []

    filtered_history = [
        item for item in raw_history
        if isinstance(item, dict) and same_sender_name(item.get("senderName"), target_sender_name)
    ]
    window_alerts = filter_window(filtered_history, window_hours, now_dt)

    enriched: List[Dict[str, Any]] = []

    for alert in window_alerts:
        if not isinstance(alert, dict):
            continue

        onset_dt = parse_iso(alert.get("onset") or alert.get("sent"))
        sent_dt = parse_iso(alert.get("sent"))
        expires_dt = parse_iso(alert.get("expires"))

        status_vigencia = classify_status(now_dt, onset_dt, expires_dt)
        uf = derive_uf(alert)
        region = (alert.get("region") or UF_TO_REGION.get(uf) or "").strip()
        dur_min = duration_minutes(onset_dt, expires_dt)
        since_min = time_since_minutes(now_dt, onset_dt)

        item = apply_municipality_metadata(dict(alert), municipalities)
        affected_municipios = normalize_affected_municipalities(item)
        affected_ids = [m["municipio_id"] for m in affected_municipios if m.get("municipio_id")]
        affected_names = [m["municipio_nome"] for m in affected_municipios if m.get("municipio_nome")]

        item.update({
            "uf": "ES",
            "uf_hint": "ES",
            "region": region or "SE",
            "location": item.get("municipio_nome") or derive_location(alert),
            "event_short": short_event(alert.get("event")),
            "category": alert.get("category") or event_category_fallback(alert.get("event")),
            "status_vigencia": status_vigencia,
            "status": status_vigencia,
            "date": onset_dt.strftime("%d/%m/%Y") if onset_dt else "--/--/----",
            "time": onset_dt.strftime("%H:%M") if onset_dt else "--:--",
            "sent_br": sent_dt.isoformat() if sent_dt else None,
            "onset_br": onset_dt.isoformat() if onset_dt else None,
            "expires_br": expires_dt.isoformat() if expires_dt else None,
            "duration_minutes": dur_min,
            "duration_hours": round(dur_min / 60, 2) if dur_min is not None else None,
            "duration_bucket": duration_bucket(dur_min),
            "time_since_minutes": since_min,
            "time_since_hours": round(since_min / 60, 2) if since_min is not None else None,
            "time_since_bucket": time_since_bucket(since_min),
            "is_active": status_vigencia == "vigente",
            "affected_municipios": affected_municipios,
            "affected_municipio_ids": affected_ids,
            "affected_municipio_names": affected_names,
            "municipios_count": len(affected_municipios),
            "_onset_dt": onset_dt,
            "_expires_dt": expires_dt,
        })

        enriched.append(item)

    default_dt = datetime.min.replace(tzinfo=TZ_BRASILIA)
    enriched.sort(key=lambda a: a.get("_onset_dt") or default_dt, reverse=True)

    counter_emitters = Counter(a.get("senderName") or "Emissor não informado" for a in enriched)
    counter_levels = Counter(a.get("nivel") or "Indefinido" for a in enriched)
    counter_events = Counter(a.get("event_short") or short_event(a.get("event")) for a in enriched)
    counter_uf = Counter(a.get("uf") for a in enriched if a.get("uf"))
    counter_municipio, affected_municipio_keys = count_affected_municipalities(enriched)
    counter_status = Counter(a.get("status_vigencia") or "sem_validade" for a in enriched)
    counter_category = Counter(category_label(a.get("category")) for a in enriched)
    counter_duration = Counter(a.get("duration_bucket") or "Sem validade" for a in enriched)
    counter_since = Counter(a.get("time_since_bucket") or "Sem data" for a in enriched)
    counter_channel = Counter(a.get("channel_list") or "Não informado" for a in enriched)

    top_events = counter_events.most_common(6)
    other_event_count = sum(counter_events.values()) - sum(count for _, count in top_events)
    if other_event_count > 0:
        top_events.append(("Outros", other_event_count))

    all_alerts = []
    for item in enriched:
        clean = dict(item)
        clean.pop("_onset_dt", None)
        clean.pop("_expires_dt", None)
        all_alerts.append(clean)

    cards = {
        "vigentes": counter_status.get("vigente", 0),
        "ultimas24h": len(enriched),
        "autoridadesAtivas": len(counter_emitters),
        "alertasExtremos": counter_levels.get("Extremo", 0),
        "alertasSeveros": counter_levels.get("Severo", 0),
        "alertasSeverosExtremos": counter_levels.get("Severo", 0) + counter_levels.get("Extremo", 0),
        "estadosComAlerta": len(counter_uf),
        "municipiosOuAreasComAlerta": len(affected_municipio_keys),
        "municipiosComAlertas": len(affected_municipio_keys),
    }

    return {
        "generated_at": now_dt.isoformat(),
        "source": str(history_path),
        "target_senderName": target_sender_name,
        "window_hours": window_hours,
        "geo": {
            "uf": "ES",
            "estado": "Espírito Santo",
            "municipios_total": len(municipalities),
            "municipios_geojson": "data/geojs-es.json",
            "alertas_geojson": "data/alertas_idap.geojson",
        },
        "municipios": municipalities,
        "cards": cards,

        "latest_alerts": [make_latest_item(a) for a in enriched[:10]],

        "top_emitters": [
            {
                "name": name,
                "short_name": short_emitter(name),
                "count": count,
            }
            for name, count in counter_emitters.most_common(10)
        ],

        "level_distribution": [
            {"label": level, "count": counter_levels.get(level, 0)}
            for level in NIVEL_ORDER
            if counter_levels.get(level, 0) > 0
        ],

        "event_distribution": [
            {"label": label, "count": count}
            for label, count in top_events
        ],

        "uf_distribution": [
            {"uf": uf, "count": count}
            for uf, count in counter_uf.most_common()
        ],

        "municipio_distribution": [
            {"municipio": municipio, "count": count}
            for municipio, count in counter_municipio.most_common()
        ],

        "status_distribution": [
            {"label": label, "count": counter_status.get(label, 0)}
            for label in STATUS_ORDER
            if counter_status.get(label, 0) > 0
        ],

        "category_distribution": [
            {"label": label, "count": count}
            for label, count in counter_category.most_common()
        ],

        "duration_distribution": [
            {"label": label, "count": count}
            for label, count in counter_duration.most_common()
        ],

        "time_since_distribution": [
            {"label": label, "count": count}
            for label, count in counter_since.most_common()
        ],

        "channel_distribution": [
            {"label": label, "count": count}
            for label, count in counter_channel.most_common()
        ],

        "all_alerts": all_alerts,
    }


def main() -> None:
    history_path = Path(os.getenv("HISTORY_PATH", DEFAULT_HISTORY_PATH))
    site_dir = Path(os.getenv("SITE_DIR", DEFAULT_SITE_DIR))
    window_hours = int(os.getenv("WINDOW_HOURS", str(DEFAULT_WINDOW_HOURS)))
    target_sender_name = os.getenv("TARGET_SENDER_NAME", DEFAULT_TARGET_SENDER_NAME).strip()

    geojson_source = Path(os.getenv("UF_GEOJSON_PATH", DEFAULT_GEOJSON_SOURCE))
    geojson_target = Path(os.getenv("DASHBOARD_GEOJSON_TARGET", DEFAULT_GEOJSON_TARGET))
    municipalities_path = Path(os.getenv("MUNICIPALITIES_GEOJSON_PATH", str(geojson_source)))

    site_dir.mkdir(parents=True, exist_ok=True)

    data = build_dashboard(history_path, window_hours, municipalities_path, target_sender_name)
    out_path = site_dir / "dashboard_data.json"
    update_path = site_dir / "ultima_atualizacao.json"
    save_json(out_path, data)
    save_json(update_path, {
        "gerado_em": data["generated_at"],
        "fonte": "scripts/build_dashboard.py",
    })

    if geojson_source.exists() and geojson_source.resolve() != geojson_target.resolve():
        geojson_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(geojson_source, geojson_target)

    print("[INFO] dashboard_data.json gerado com sucesso")
    print(f"[INFO] arquivo: {out_path}")
    print(f"[INFO] última atualização: {update_path}")
    print(f"[INFO] alertas no período: {len(data.get('all_alerts', []))}")
    print(f"[INFO] municípios carregados: {len(data.get('municipios', []))}")

    if geojson_source.exists() and geojson_source.resolve() != geojson_target.resolve():
        print(f"[INFO] geojson copiado para: {geojson_target}")


if __name__ == "__main__":
    main()
