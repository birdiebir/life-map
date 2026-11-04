r"""「下次去哪」：規則式建議，不用 AI（規格書 §8）。

1. 快完成的套組：完成比例最高、還沒滿的套組，列離家最近的幾個缺口
2. 週末就能去：離家 weekend_km 內還沒去過的台灣景點（tier1、tier2 優先）
3. 順路收集鄉鎮：跟去過的鄉鎮相鄰（代表點距離 neighbor_km 內）但還沒去過的鄉鎮
4. 值得再深玩：只到「路過／踏上」的地方
5. 還沒一起去過：自己玩過（≥3 級）但還沒跟伴侶一起去的地方
6. 下一個國外目標：沒去過的精選城市（排名在前、離家近的優先）
家的位置：<資料夾>\settings.json 的 home_place；沒有就用最近的「住過」台灣鄉鎮。
"""
from __future__ import annotations

from .data import Visit
from .geo import haversine_km
from .reference import Place
from .sets import set_members

DEFAULTS = {"weekend_km": 150, "neighbor_km": 12, "per_section": 6, "almost_sets": 3, "almost_min_ratio": 0.5}
SET_LABEL = {"national_park": "國家公園", "national_nature_park": "國家自然公園", "national_scenic_area": "國家風景區",
             "county_highlight": "縣市代表景點", "baiyue": "百岳", "old_street": "老街", "island": "離島"}


def home_place(visits: list[Visit], places: dict[str, Place], settings: dict) -> Place | None:
    pid = settings.get("home_place")
    if pid in places and places[pid].lat is not None:
        return places[pid]
    lived = [v for v in visits if v.level >= 5 and v.confirmed and places[v.place_id].kind == "tw_town"
             and places[v.place_id].lat is not None]
    if not lived:
        return None
    # 最近開始住的（有日期的排前面，日期新的優先）
    lived.sort(key=lambda v: (bool(v.date_start) and not v.date_end, v.date_start), reverse=True)
    return places[lived[0].place_id]


def _dist(home: Place | None, p: Place) -> float:
    if home is None or p.lat is None:
        return 1e9
    return haversine_km(home.lat, home.lon, p.lat, p.lon)


def _item(p: Place, why: str, home: Place | None) -> dict:
    d = _dist(home, p)
    return {"pid": p.id, "name": p.name, "why": why + (f"・離家約 {d:.0f} km" if d < 1e8 else "")}


def recommend(places: dict[str, Place], lv_me: dict[str, int], lv_together: dict[str, int],
              progress: list[dict], sets_cfg: list[dict], visits: list[Visit], settings: dict,
              cfg: dict | None = None,
              city_rank: dict[str, int] | None = None, min_level: int = 2) -> list[dict]:
    cfg = {**DEFAULTS, **(cfg or {})}
    n = cfg["per_section"]
    home = home_place(visits, places, settings)
    city_rank = city_rank or {}
    been = {pid for pid, lv in lv_me.items() if lv >= min_level}
    sections = []

    # 1. 快完成的套組
    almost = []
    candidates = [s for s in progress if s["id"] != "continents" and s["total"]
                  and cfg["almost_min_ratio"] <= s["done"] / s["total"] < 1]
    for s in sorted(candidates, key=lambda s: s["done"] / s["total"], reverse=True)[: cfg["almost_sets"]]:
        s_cfg = next(c for c in sets_cfg if c["id"] == s["id"])
        missing = [places[pid] for pid in set_members(s_cfg, places) if pid not in been and places[pid].lat is not None]
        missing.sort(key=lambda p: (_dist(home, p), p.name))
        for p in missing[:2]:
            almost.append(_item(p, f"{s['name']} {s['done']}/{s['total']}，再 {s['total'] - s['done']} 個就收齊", home))
    if almost:
        sections.append({"title": "快完成的套組", "items": almost[:n]})

    # 2. 週末就能去
    pois = [p for p in places.values() if p.kind == "tw_poi" and p.id not in been and _dist(home, p) <= cfg["weekend_km"]]
    pois.sort(key=lambda p: (0 if "tier1" in p.tags else 1 if "tier2" in p.tags else 2, _dist(home, p)))
    if pois:
        sections.append({"title": "週末就能去", "items": [
            _item(p, "、".join(SET_LABEL[t] for t in p.tags if t in SET_LABEL) or "景點", home) for p in pois[:n]]})

    # 3. 順路收集鄉鎮
    visited_towns = [places[pid] for pid in been if places[pid].kind == "tw_town" and places[pid].lat is not None]
    near = []
    for p in places.values():
        if p.kind != "tw_town" or p.id in been or p.lat is None:
            continue
        best = min(((haversine_km(p.lat, p.lon, t.lat, t.lon), t) for t in visited_towns), default=None,
                   key=lambda x: x[0])
        if best and best[0] <= cfg["neighbor_km"]:
            near.append((p, best[1]))
    near.sort(key=lambda x: _dist(home, x[0]))
    if near:
        sections.append({"title": "順路收集鄉鎮", "items": [
            _item(p, f"{places[p.parent].name}，就在去過的{t.name}旁邊", home) for p, t in near[:n]]})

    # 4. 值得再深玩
    shallow = [places[pid] for pid, lv in lv_me.items()
               if 1 <= lv <= 2 and places[pid].kind in ("city", "tw_county", "tw_poi", "whs")]
    shallow.sort(key=lambda p: _dist(home, p))
    if shallow:
        sections.append({"title": "值得再深玩", "items": [
            _item(p, f"目前只到「{'路過' if lv_me[p.id] == 1 else '踏上'}」", home) for p in shallow[:n]]})

    # 5. 還沒一起去過
    solo = [places[pid] for pid, lv in lv_me.items()
            if lv >= 3 and not lv_together.get(pid) and places[pid].kind in ("city", "tw_county", "tw_poi", "whs")]
    solo.sort(key=lambda p: (-lv_me[p.id], _dist(home, p)))
    if solo:
        sections.append({"title": "還沒一起去過", "items": [_item(p, "自己玩過，還沒一起去", home) for p in solo[:n]]})

    # 6. 下一個國外目標
    cities = [p for p in places.values() if p.kind == "city" and "curated" in p.tags and p.id not in been]
    cities.sort(key=lambda p: (city_rank.get(p.id, 999), _dist(home, p)))
    if cities:
        sections.append({"title": "下一個國外目標", "items": [
            _item(p, (f"Euromonitor 旅客量 #{city_rank[p.id]}" if p.id in city_rank else "精選城市")
                  + f"・{places[p.parent].name}", home) for p in cities[:n]]})
    # 同一個地方只出現在第一個分類
    seen, out = set(), []
    for sec in sections:
        items = [i for i in sec["items"] if i["pid"] not in seen]
        seen.update(i["pid"] for i in items)
        if items:
            out.append({**sec, "items": items})
    return out
