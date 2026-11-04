"""把足跡、參考資料、地圖形狀和 D3 組成一個離線、自包含的 HTML。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .data import load_trips, load_visits
from .levels import ancestors, place_levels
from .pending import NO, read_rows
from .recommend import recommend
from .reference import Place, load_places
from .sets import set_progress, scores

TEMPLATE = Path(__file__).with_name("template.html")


def _photo_uri(photo: str, data_dir: Path) -> str:
    if not photo or photo.startswith("zip:"):
        return ""
    p = Path(photo)
    if not p.is_absolute():
        p = data_dir / p
    return p.as_uri()


def build_payload(data_dir: Path, ref_dir: Path, levels_cfg: dict, sets_cfg: list, score_cfg: dict, *,
                  include_unconfirmed: bool = False, places: dict[str, Place] | None = None,
                  rec_cfg: dict | None = None, ach_domains=None) -> dict:
    places = places or load_places(ref_dir)
    visits = load_visits(data_dir / "visits.csv", places)
    # 關掉的套組（enabled=false）底下的景點不顯示、不算、不推薦；去過的照樣保留
    off_tags = {c["tag"] for c in sets_cfg if c.get("enabled") is False and c.get("tag")}
    visited_ids = {v.place_id for v in visits}
    places = {k: p for k, p in places.items()
              if not (p.kind == "tw_poi" and p.tags & off_tags and k not in visited_ids)}
    pending_rows = [r for r in read_rows(data_dir / "pending.csv") if r.get("decision", "").lower() not in NO]
    if include_unconfirmed and pending_rows:
        open_ids = {r["visit_id"] for r in pending_rows}
        visits += [v for v in load_visits(data_dir / "pending.csv", places) if v.visit_id in open_ids]
    trips = load_trips(data_dir / "trips.csv")
    min_level = levels_cfg["visited_min_level"]
    score_kinds = {k: v for k, v in score_cfg.items() if isinstance(v, list)}

    lv, prog, sc = {}, {}, {}
    for who, together_only in (("me", False), ("together", True)):
        lv[who] = place_levels(visits, places, include_unconfirmed=include_unconfirmed, together_only=together_only)
        prog[who] = set_progress(sets_cfg, places, lv[who], min_level)
        sc[who] = scores(score_kinds, places, lv[who])

    shown = [v for v in visits if v.confirmed or include_unconfirmed]
    visited_cities = {v.place_id for v in shown if places[v.place_id].kind == "city"}
    out_places = {}
    for p in places.values():
        # 沒去過的城市只放精選城市（地圖上當「待收集」），其他不放，控制檔案大小
        if p.kind == "city" and p.id not in visited_cities and "curated" not in p.tags:
            continue
        d = {"n": p.name, "k": p.kind}
        if p.parent:
            d["p"] = p.parent
        if p.continent:
            d["c"] = p.continent
        if p.lat is not None:
            d["lat"], d["lon"] = round(p.lat, 4), round(p.lon, 4)
        if p.tags:
            d["t"] = sorted(p.tags)
        out_places[p.id] = d

    settings_file = data_dir / "settings.json"
    settings = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.exists() else {}
    city_rank = {}
    if (ref_dir / "world" / "curated_cities.csv").exists():
        city_rank = {r["city_id"]: int(r["euromonitor_rank"]) for r in read_rows(ref_dir / "world" / "curated_cities.csv")
                     if r.get("euromonitor_rank", "").isdigit()}
    recs = {w: recommend(places, lv["me"] if w == "me" else lv["together"], lv["together"], prog[w], sets_cfg,
                         shown, settings, rec_cfg, city_rank, min_level) for w in ("me", "together")}

    payload = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "levels": levels_cfg["levels"],
        "minLevel": min_level,
        "places": out_places,
        "lv": lv,
        "sets": {w: [{k: v for k, v in s.items() if k != "members_done"} for s in prog[w]] for w in prog},
        "recs": recs,
        "scores": sc,
        # 待確認＝visits.csv 裡 confirmed=false 的＋pending.csv 還沒填「不收」的（不論這次有沒有畫進來）
        "unconfirmed": sum(1 for v in visits if not v.confirmed and not v.visit_id.startswith("P"))
                       + len(pending_rows),
        "visits": [{"id": v.visit_id, "pid": v.place_id, "ds": v.date_start, "de": v.date_end, "lv": v.level,
                    "tg": v.together, "trip": v.trip_id, "mem": v.memory, "photo": _photo_uri(v.photo, data_dir),
                    "src": v.source, "ok": v.confirmed, "anc": ancestors(v.place_id, places)} for v in shown],
        "trips": {t.trip_id: {"name": t.name, "ds": t.date_start, "de": t.date_end, "with": t.companions,
                              "kind": t.kind} for t in trips.values()},
    }
    if ach_domains is not None:
        payload["ach"] = _ach(data_dir, ach_domains, places, lv["me"], sc["me"], shown, min_level, include_unconfirmed, trips)
    return payload


def _ach(data_dir, domains, places, my_lv, my_score, shown, min_level, include_pending, trips=None):
    from .ach_view import build_ach_payload
    countries = [l for pid, l in my_lv.items() if pid in places and places[pid].kind == domains.travel_kind]
    dated = [v for v in shown if v.date_start]
    last = max(dated, key=lambda v: (v.date_start, v.visit_id), default=None)
    travel = {"levels": countries, "xp": my_score.get("world", 0),
              "unlocked": sum(1 for l in countries if l >= min_level),
              "latest": {"title": places[last.place_id].name, "date": last.date_start} if last else None}
    return build_ach_payload(data_dir, domains, travel=travel, include_pending=include_pending, trips=trips)


def _js(obj) -> str:
    # 避免資料裡出現 </script> 截斷頁面
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_html(payload: dict, ref_dir: Path, vendor_dir: Path) -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    parts = {
        "/*__D3__*/": (vendor_dir / "d3.min.js").read_text(encoding="utf-8"),
        "/*__TOPOJSON__*/": (vendor_dir / "topojson-client.min.js").read_text(encoding="utf-8"),
        "/*__WORLD__*/": (ref_dir / "world" / "countries-50m.json").read_text(encoding="utf-8"),
        "/*__TAIWAN__*/": (ref_dir / "taiwan" / "taiwan-10t.json").read_text(encoding="utf-8"),
        "/*__DATA__*/": _js(payload),
    }
    for key, value in parts.items():
        if key not in html:
            raise ValueError(f"template 少了 {key}")
        html = html.replace(key, value, 1)
    return html
