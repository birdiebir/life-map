"""套組完成度與經驗值分數。

套組設定（config\sets.json）每一項：
- kind=continents：七大洲（看去過的國家）
- kind=places：place_kind 這一類的地點；可加 tag 只算有該標籤的（例如精選城市、tier1 景點）
- enabled=false 不顯示；min_level 可覆寫「去過」門檻
參考資料還沒有的套組（成員 0 個）會自動略過。
"""
from __future__ import annotations

from .reference import Place

CONTINENTS = {"AS": "亞洲", "EU": "歐洲", "AF": "非洲", "NA": "北美洲", "SA": "南美洲", "OC": "大洋洲", "AN": "南極洲"}


def set_members(s: dict, places: dict[str, Place]) -> list[str]:
    return [p.id for p in places.values()
            if p.kind == s["place_kind"] and (not s.get("tag") or s["tag"] in p.tags)]


def set_progress(sets_cfg: list[dict], places: dict[str, Place], levels: dict[str, int],
                 min_level: int) -> list[dict]:
    """去過＝等級 ≥ min_level（預設 2：轉機、路過不算去過，但仍算分數）。"""
    out = []
    for s in sets_cfg:
        if s.get("enabled") is False:
            continue
        need = s.get("min_level", min_level)
        if s["kind"] == "continents":
            done = sorted({places[pid].continent for pid, lv in levels.items()
                           if lv >= need and places[pid].kind == "country" and places[pid].continent})
            members_done, total = done, len(CONTINENTS)
        else:
            members = set_members(s, places)
            if not members:
                continue
            members_done = [pid for pid in members if levels.get(pid, 0) >= need]
            total = len(members)
        out.append({"id": s["id"], "name": s["name"], "done": len(members_done), "total": total,
                    "members_done": members_done, "scope": s.get("scope", "")})
    return out


def scores(score_cfg: dict[str, list[str]], places: dict[str, Place], levels: dict[str, int]) -> dict[str, int]:
    return {name: sum(lv for pid, lv in levels.items() if places[pid].kind in kinds)
            for name, kinds in score_cfg.items()}
