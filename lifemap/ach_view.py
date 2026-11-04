r"""人生成就分頁要用的資料（給 HTML 的 payload["ach"]）。

- 讀 achievements.csv、achievement_suppress.json；預覽時（include_pending）把 pending_achievements.csv
  裡「有填等級、沒被否決」的候選當未確認紀錄一起算，卡片標「待確認」。
- 「不再提起」的照算等級、經驗值、雷達，但不出現在卡牆、依年份、最近一張卡。
- 旅遊軸＝旅遊地圖「國家」層級等級前 top_n 名平均（取法在 config\domains.json 的 radar）。
"""
from __future__ import annotations

import re
from pathlib import Path

from .ach_stats import _sort_key, domain_xp, item_levels, radar, set_grid
from .achievements import (DATE_RE, Achievement, Domains, is_suppressed, load_achievements, load_suppress_rules,
                           _bounds)
from .pending import NO, YES, read_rows

TRAVEL_ID = "travel"
TRAVEL_NAME = "旅遊"


def pending_candidates(path: Path, domains: Domains, existing_ids: set[str]) -> list[Achievement]:
    """level 有填、decision 不是 n，而且（decision 是 y 或 suggest 不是 n）的候選列。"""
    out: list[Achievement] = []
    for r in read_rows(path):
        decision, suggest = r.get("decision", "").lower(), r.get("suggest", "").lower()
        if r.get("achievement_id", "") in existing_ids or r.get("domain") not in domains.by_id:
            continue
        if decision in NO or not (decision in YES or suggest not in NO):
            continue
        try:
            level = int(r.get("level", ""))
        except ValueError:
            continue
        if not 0 <= level <= 5:
            continue
        date = r.get("date", "")
        out.append(Achievement(r["achievement_id"], r["domain"], r.get("item", ""), r.get("title", ""), level,
                               date if DATE_RE.match(date) else "",
                               (r.get("together", "").lower() in YES), r.get("memory", ""), r.get("photo", ""),
                               r.get("source", ""), r.get("origin", ""), r.get("confidence", ""), False,
                               r.get("privacy", ""), (r.get("suppressed", "").lower() in YES)))
    return out


_TRIP_SRC = re.compile(r"^trips\.csv#(.+)$")


def _trip_of(a: Achievement, trips) -> dict | None:
    """出處是 trips.csv#<id> 且旅程表裡有這趟，才回傳 {id, name}（卡片與旅遊地圖互相連結用）。"""
    m = _TRIP_SRC.match(a.source or "")
    t = (trips or {}).get(m.group(1)) if m else None
    return {"id": t.trip_id, "name": t.name} if t else None


def _card(a: Achievement, domains: Domains, trips=None) -> dict:
    c = {"id": a.achievement_id, "domain": a.domain, "domain_name": domains.by_id[a.domain].name,
         "item": a.item, "title": a.title, "level": a.level, "date": a.date, "memory": a.memory,
         "source": a.source, "together": a.together, "pending": not a.confirmed}
    trip = _trip_of(a, trips)
    if trip:
        c["trip"] = trip
    return c


def _travel(travel, n: int, min_level: int) -> dict:
    info = travel if isinstance(travel, dict) else {"levels": list(travel or [])}
    levels = sorted((int(x) for x in info.get("levels", [])), reverse=True)
    value = sum(levels[:n]) / n if n else 0
    latest = info.get("latest")
    return {"id": TRAVEL_ID, "name": TRAVEL_NAME, "xp": info.get("xp", sum(levels)),
            "unlocked": info.get("unlocked", sum(1 for x in levels if x >= min_level)),
            "level": levels[0] if levels else 0, "latest": latest, "value": value}


def build_ach_payload(data_dir: Path, domains: Domains, *, travel=None, include_pending: bool = False,
                      trips=None) -> dict:
    data_dir = Path(data_dir)
    ach_path = data_dir / "achievements.csv"
    achs = load_achievements(ach_path, domains) if ach_path.exists() else []
    rules = load_suppress_rules(data_dir / "achievement_suppress.json")
    pend = (pending_candidates(data_dir / "pending_achievements.csv", domains, {a.achievement_id for a in achs})
            if include_pending else [])
    everything = achs + pend

    levels = item_levels(everything, include_unconfirmed=include_pending)
    xp = domain_xp(levels, domains)
    grids = set_grid(domains, levels)
    axis = radar(levels, domains)
    cards = sorted((a for a in everything if (a.confirmed or include_pending) and not is_suppressed(a, rules)),
                   key=_sort_key)

    out_domains = []
    for did, dom in domains.by_id.items():
        mine = [a for a in cards if a.domain == did]
        dated = [a for a in mine if a.date]
        latest = max(dated, key=lambda a: (_bounds(a.date)[1], a.achievement_id)) if dated else None
        items = [lv for (d, _i), lv in levels.items() if d == did]
        out_domains.append({
            "id": did, "name": dom.name, "xp": xp[did], "unlocked": sum(1 for lv in items if lv >= domains.visited_min_level),
            "level": max(items, default=0), "value": axis[did],
            "latest": {"title": latest.title, "date": latest.date} if latest else None,
            "level_defs": {str(k): v for k, v in dom.levels.items()},
            "sets": grids[did], "cards": [_card(a, domains, trips) for a in mine],
        })

    t = _travel(travel, domains.top_n, domains.visited_min_level)
    years: dict[str, list[dict]] = {}
    for a in cards:
        years.setdefault(a.date[:4], []).append(_card(a, domains, trips))
    by_trip: dict[str, list[dict]] = {}
    for a in cards:                       # 旅遊地圖彈出視窗用：旅程 → 家人成就（只含卡牆會顯示的）
        trip = _trip_of(a, trips)
        if trip:
            by_trip.setdefault(trip["id"], []).append({"id": a.achievement_id, "title": a.title, "domain": a.domain})
    return {
        "domains": out_domains,
        "by_trip": by_trip,
        "travel": t,
        "radar": [{"id": TRAVEL_ID, "name": TRAVEL_NAME, "value": t["value"]}]
                 + [{"id": d["id"], "name": d["name"], "value": d["value"]} for d in out_domains],
        "by_year": [{"year": y or "未記日期", "cards": c} for y, c in years.items()],
        "pending_count": len(pend), "preview": bool(include_pending),
    }
