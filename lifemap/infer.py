"""觀察點（評論、照片）→ 候選足跡。

1. 每個點判斷地點（台灣到鄉鎮、其他到城市）；只有國碼、沒有座標的評論（例如線上服務）不產生候選。
2. 同一範圍（台灣看縣市、國外看國家）的點，間隔不超過 trip_gap_days 天就算同一趟。
3. 同一趟裡同一個地點：出現在 2 天以上 → 4 過夜；同一天 2 筆以上 → 3 遊玩；只有 1 筆 → 2 踏上。
4. 依查核加的修正：
   - 評論日期是寫評論的日子，不一定是到訪日：本國只有評論的候選最多推 2；
     那天人住在國外（已確認的「住過」期間）→ 日期清空、信心低；同一天跨縣市的評論 → 信心低。
   - 住家所在縣市（當時有「住過」紀錄）不同天出現不推 4 過夜。
   - 同一個國外城市幾個月內反覆出現 → 合成一筆並提示「可能住過」。
   - 落在已知長期居住期間（例如留學）的國外候選，掛到那趟旅程，不另開自動旅程。
   - 到府、代辦性質的店家（名稱關鍵字在 config）信心降低。
5. 已經有足跡涵蓋（同地點、等級不低於推定、日期重疊或沒記日期）的跳過。
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import replace
from datetime import date

from .data import Visit
from .geo import Location, Locator
from .reference import Place
from .takeout import Observation

DEFAULT_RULES = {
    "home_country": "C-TWN",
    "review_only_max_level_home": 2,
    "long_stay_min_visits": 3,
    "long_stay_months": 8,
    "low_confidence_keywords": ["工程行", "水電", "搬家", "寬頻", "托嬰", "清潔", "Service"],
}


def date_range(ds: str, de: str) -> tuple[str, str] | None:
    """把 YYYY／YYYY-MM／YYYY-MM-DD 轉成可比較的區間；沒有日期回傳 None（視為涵蓋所有時間）。"""
    if not ds:
        return None
    end = de or ds

    def lo(s: str) -> str:
        return {4: s + "-01-01", 7: s + "-01"}.get(len(s), s)

    def hi(s: str) -> str:
        return {4: s + "-12-31", 7: s + "-31"}.get(len(s), s)

    return lo(ds), hi(end)


def _within(r: tuple[str, str] | None, day: str) -> bool:
    return r is None or r[0] <= day <= r[1]


def covered(existing: list[Visit], place_id: str, level: int, ds: str, de: str) -> bool:
    cand = date_range(ds, de)
    for v in existing:
        if v.place_id != place_id or v.level < level:
            continue
        r = date_range(v.date_start, v.date_end)
        if r is None or cand is None or (r[0] <= cand[1] and cand[0] <= r[1]):
            return True
    return False


def _residences(existing: list[Visit], places: dict[str, Place]) -> list[dict]:
    """已確認「住過」（5 級）的地點：所屬國家、台灣縣市、期間（沒日期＝一直）、旅程。"""
    out = []
    for v in existing:
        if v.level < 5 or not v.confirmed:
            continue
        chain = [v.place_id]
        p = places[v.place_id]
        while p.parent and p.parent in places:
            chain.append(p.parent)
            p = places[p.parent]
        country = next((c for c in chain if places[c].kind == "country"), None)
        county = next((c for c in chain if places[c].kind == "tw_county"), None)
        out.append({"country": country, "county": county, "range": date_range(v.date_start, v.date_end),
                    "dated": bool(v.date_start), "trip": v.trip_id})
    return out


def _clusters(days: list[date], gap: int) -> list[list[int]]:
    order = sorted(range(len(days)), key=lambda i: days[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and (days[i] - days[groups[-1][-1]]).days <= gap:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def candidate_id(place_id: str, ds: str, de: str) -> str:
    return "P" + hashlib.sha1(f"{place_id}|{ds}|{de}".encode()).hexdigest()[:8]


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def build_candidates(obs: list[Observation], locator: Locator, places: dict[str, Place],
                     existing: list[Visit], gap_days: int, rules: dict | None = None,
                     crossings: list[tuple[str, str]] | None = None) -> tuple[list[dict], dict]:
    """crossings：出入境紀錄 [(出境日, 入境日)]，有的話用來判斷「那天人在不在國內」。"""
    rules = {**DEFAULT_RULES, **(rules or {}), "_crossings": crossings or []}
    home = rules["home_country"]
    residences = _residences(existing, places)
    stats = {"observations": len(obs), "unlocated": 0, "no_coordinates": 0, "covered": 0}

    located: list[tuple[Observation, Location]] = []
    for o in obs:
        if o.lat is None or o.lon is None:
            stats["no_coordinates"] += 1
            continue
        loc = locator.locate(o.lat, o.lon, o.country_hint)
        if loc is None:
            stats["unlocated"] += 1
            continue
        located.append((o, loc))
        if hasattr(locator, "pois_near"):
            located += [(o, replace(loc, poi=pid)) for pid in locator.pois_near(o.lat, o.lon)]

    # 同一天在 2 個以上縣市寫評論 → 多半是事後補寫
    review_counties: dict[date, set[str]] = defaultdict(set)
    for o, loc in located:
        if o.source == "review" and loc.tw_county and not loc.poi:
            review_counties[o.day].add(loc.tw_county)
    multi_county_days = {d for d, cs in review_counties.items() if len(cs) >= 2}

    by_region: dict[str, list[tuple[Observation, Location]]] = defaultdict(list)
    for o, loc in located:
        by_region[loc.region].append((o, loc))

    raw = []
    for region, items in by_region.items():
        for group in _clusters([o.day for o, _ in items], gap_days):
            by_place: dict[str, list[Observation]] = defaultdict(list)
            for i in group:
                o, loc = items[i]
                by_place[loc.place_id].append(o)
            first = min(items[i][0].day for i in group).isoformat()
            loc0 = items[group[0]][1]
            country = loc0.country
            trip = ""
            if country != home:
                long_trip = next((r["trip"] for r in residences if r["country"] == country and r["dated"]
                                  and r["trip"] and _within(r["range"], first)), "")
                trip = long_trip or f"A-{country[2:]}-{first[:4]}{first[5:7]}"
            for pid, os_ in by_place.items():
                raw.append(_row(pid, os_, country, loc0.tw_county, trip, places, residences, rules,
                                multi_county_days))
    rows = _merge_pois(_merge_long_stays(raw, home, rules))

    out = []
    for r in rows:
        if covered(existing, r["place_id"], r["level"], r["date_start"], r["date_end"]):
            stats["covered"] += 1
            continue
        r["visit_id"] = r.pop("_id")
        r["evidence"] = "；".join([f"評論 {r.pop('_rev')}、照片 {r.pop('_pho')}", *r.pop("_notes")])
        out.append(r)
    out.sort(key=lambda r: (r["date_start"], r["place_id"]))
    stats["candidates"] = len(out)
    return out, stats


def _row(pid, os_, country, county, trip, places, residences, rules, multi_county_days) -> dict:
    days = sorted({o.day for o in os_})
    level = 4 if len(days) >= 2 else 3 if len(os_) >= 2 else 2
    ds, de = days[0].isoformat(), days[-1].isoformat()
    cid = candidate_id(pid, ds, de)  # 用原始日期算，之後清空日期也不會撞號
    n_rev = sum(o.source == "review" for o in os_)
    n_pho = sum(o.source == "photo" for o in os_)
    review_only = n_pho == 0
    labels = list(dict.fromkeys(o.label for o in os_ if o.label))
    conf = "中" if level >= 3 else "低"
    notes: list[str] = []

    if country == rules["home_country"] and review_only and level > rules["review_only_max_level_home"]:
        level = rules["review_only_max_level_home"]
        notes.append("只有評論，等級最多推 2")
    if county and level == 4 and any(r["county"] == county and _within(r["range"], ds) for r in residences):
        level = 3
        notes.append("住家所在縣市，不同天不算過夜")
    crossings = rules["_crossings"]
    abroad_that_day = any(a < ds < b for a, b in crossings)
    if crossings and country != rules["home_country"] and not any(a <= ds <= b for a, b in crossings):
        conf = "低"
        notes.append("出入境紀錄沒有這段出國")
    if review_only and (abroad_that_day and country == rules["home_country"] or any(
            r["country"] and r["country"] != country and r["dated"] and _within(r["range"], ds) for r in residences)):
        ds = de = ""
        conf = "低"
        notes.append("評論日期非到訪日（那時住在國外）")
    elif review_only and county and any(d in multi_county_days for d in days):
        conf = "低"
        notes.append("同一天跨縣市評論，可能是事後補寫")
    if any(k.lower() in lab.lower() for lab in labels for k in rules["low_confidence_keywords"]):
        conf = "低"
        notes.append("到府／代辦類店家，可能沒去過")

    photo = next((o.ref for o in sorted(os_, key=lambda o: o.day) if o.source == "photo" and o.ref), "")
    return {
        "place_id": pid, "date_start": ds, "date_end": de if de != ds else "", "level": level,
        "together": "false", "trip_id": trip, "memory": "、".join(labels[:4]) + ("…" if len(labels) > 4 else ""),
        "photo": photo, "source": "+".join(s for s, n in (("review", n_rev), ("photo", n_pho)) if n),
        "confidence": conf, "confirmed": "false", "place_name": _full_name(pid, places), "decision": "",
        "_rev": n_rev, "_pho": n_pho, "_notes": notes, "_id": cid,
    }


def _merge_long_stays(rows: list[dict], home: str, rules: dict) -> list[dict]:
    """同一個國外地點在 long_stay_months 個月內出現 long_stay_min_visits 次以上 → 合成一筆、提示可能住過。"""
    by_place: dict[str, list[dict]] = defaultdict(list)
    out = []
    for r in rows:
        if r["place_id"].startswith("CITY-") and r["date_start"] and not r["trip_id"].startswith("T"):
            by_place[r["place_id"]].append(r)
        else:
            out.append(r)
    for pid, rs in by_place.items():
        rs.sort(key=lambda r: r["date_start"])
        end = max((r["date_end"] or r["date_start"]) for r in rs)
        if len(rs) >= rules["long_stay_min_visits"] and _months_between(rs[0]["date_start"], end) <= rules["long_stay_months"]:
            m = dict(rs[0])
            m.update(date_end=end, level=max(r["level"] for r in rs), _rev=sum(r["_rev"] for r in rs),
                     _pho=sum(r["_pho"] for r in rs), confidence="中",
                     memory="、".join(dict.fromkeys(x for r in rs for x in r["memory"].split("、") if x)),
                     _notes=[f"{len(rs)} 次出現在 {_months_between(rs[0]['date_start'], end) + 1} 個月內，可能住過（要的話改 5）"])
            out.append(m)
        else:
            out.extend(rs)
    return out


def _merge_pois(rows: list[dict]) -> list[dict]:
    """景點、世界遺產只要知道去過沒有：同一個只留一筆（最早那次、最高等級），註明一共出現幾次。"""
    by_poi: dict[str, list[dict]] = defaultdict(list)
    out = []
    for r in rows:
        (by_poi[r["place_id"]] if r["place_id"].startswith(("TWP-", "WHS-")) else out).append(r)
    for pid, rs in by_poi.items():
        rs.sort(key=lambda r: r["date_start"] or "9999")
        m = dict(rs[0])
        m.update(level=max(r["level"] for r in rs), _rev=sum(r["_rev"] for r in rs),
                 _pho=sum(r["_pho"] for r in rs),
                 memory="、".join(list(dict.fromkeys(x for r in rs for x in r["memory"].split("、") if x))[:4]),
                 _notes=list(dict.fromkeys(n for r in rs for n in r["_notes"]))
                 + ([f"一共出現 {len(rs)} 次，取最早一次"] if len(rs) > 1 else []))
        if any(r["confidence"] == "中" for r in rs):
            m["confidence"] = "中"
        out.append(m)
    return out


def _full_name(pid: str, places: dict[str, Place]) -> str:
    p = places[pid]
    names = [p.name]
    while p.parent and p.parent in places:
        p = places[p.parent]
        names.append(p.name)
    return " / ".join(reversed(names))
