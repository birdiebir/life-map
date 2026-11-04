"""等級合併：地點等級＝所有足跡的最高等級，並往上層傳遞（去過大阪過夜 → 日本至少 4）。"""
from __future__ import annotations

from .data import Visit
from .reference import Place


def ancestors(place_id: str, places: dict[str, Place]) -> list[str]:
    out = []
    p = places[place_id].parent
    while p:
        out.append(p)
        p = places[p].parent if p in places else None
    return out


def place_levels(visits: list[Visit], places: dict[str, Place], *, include_unconfirmed: bool = False,
                 together_only: bool = False) -> dict[str, int]:
    levels: dict[str, int] = {}
    for v in visits:
        if not (v.confirmed or include_unconfirmed) or (together_only and not v.together) or v.level <= 0:
            continue
        for pid in [v.place_id, *ancestors(v.place_id, places)]:
            levels[pid] = max(levels.get(pid, 0), v.level)
    return levels
