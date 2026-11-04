"""成就統計：項目等級、經驗值、套組格子圖鑑、雷達、卡牆、依年份看。

規則：等級只升不降（項目等級＝已確認紀錄的最高級）；「不再提起」的紀錄照算等級、經驗值、雷達，
但不出現在卡牆、依年份看、最近一張卡。
"""
from __future__ import annotations

from .achievements import Achievement, Domains, is_suppressed, _bounds


def item_levels(achs: list[Achievement], include_unconfirmed: bool = False,
                together_only: bool = False) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for a in achs:
        if not (a.confirmed or include_unconfirmed):
            continue
        if together_only and not a.together:
            continue
        key = (a.domain, a.item)
        out[key] = max(out.get(key, 0), a.level)
    return out


def domain_xp(levels: dict, domains: Domains) -> dict[str, float]:
    xp = {did: 0 for did in domains.by_id}
    for (did, _item), lv in levels.items():
        if did in xp:
            xp[did] += domains.by_id[did].scores[lv]
    return xp


def set_grid(domains: Domains, levels: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for did, dom in domains.by_id.items():
        grids = []
        for s in dom.sets:
            cells = []
            for item in s.items:
                lv = levels.get((did, item), 0)
                cells.append({"item": item, "level": lv, "unlocked": lv >= domains.visited_min_level})
            grids.append({"id": s.id, "name": s.name, "done": sum(c["unlocked"] for c in cells),
                          "total": len(cells), "cells": cells})
        out[did] = grids
    return out


def radar(levels: dict, domains: Domains) -> dict[str, float]:
    n = domains.top_n
    out = {}
    for did in domains.by_id:
        top = sorted((lv for (d, _i), lv in levels.items() if d == did), reverse=True)[:n]
        out[did] = sum(top) / n
    return out


def _shown(achs: list[Achievement], rules: list[dict]) -> list[Achievement]:
    return [a for a in achs if a.confirmed and not is_suppressed(a, rules)]


def _sort_key(a: Achievement):
    # 同一年裡只有年份的排在有月份／日期的後面
    return (a.date == "", a.date[:4], len(a.date) == 4, _bounds(a.date)[0] if a.date else "", a.achievement_id)


def visible_cards(achs: list[Achievement], rules: list[dict]) -> list[Achievement]:
    """卡牆：依時間由舊到新，沒日期的排最後。"""
    return sorted(_shown(achs, rules), key=_sort_key)


def by_year(achs: list[Achievement], rules: list[dict]) -> dict[str, list[Achievement]]:
    groups: dict[str, list[Achievement]] = {}
    for a in visible_cards(achs, rules):
        groups.setdefault(a.date[:4], []).append(a)
    return groups


def latest_card(achs: list[Achievement], rules: list[dict], domain: str) -> Achievement | None:
    dated = [a for a in _shown(achs, rules) if a.domain == domain and a.date]
    return max(dated, key=lambda a: (_bounds(a.date)[1], a.achievement_id)) if dated else None
