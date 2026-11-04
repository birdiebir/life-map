"""成就測試共用工具（不是測試檔）。"""
from __future__ import annotations

import json
from pathlib import Path

from lifemap.achievements import ACH_FIELDS, Achievement, load_domains, load_domains_for

ROOT = Path(__file__).resolve().parent.parent
HEADER = ",".join(ACH_FIELDS) + "\n"


def real_domains():
    return load_domains_for(ROOT / "private.example")


def make_domains(scores=None, top_n=5, min_level=1, sets=None):
    scores = scores or {str(i): i for i in range(6)}
    lv = {str(i): f"L{i}" for i in range(6)}
    cfg = {
        "radar": {"top_n": top_n},
        "visited_min_level": min_level,
        "privacy_levels": ["local", "kb"],
        "domains": {
            "learning": {"name": "學習", "levels": lv, "scores": scores, "recommend": True, "privacy": "kb",
                         "sets": sets if sets is not None else [{"id": "cert", "name": "證照", "items": ["A", "B", "C"]}]},
            "sports": {"name": "運動", "levels": lv, "scores": scores, "recommend": True, "privacy": "local", "sets": []},
        },
    }
    return load_domains(cfg)


def ach(i="1", domain="learning", item="A", level=1, date="2024-01", together=False, confirmed=True,
        suppressed=False, title=None, privacy="local"):
    return Achievement(i, domain, item, title or f"t{i}", level, date, together, "", "", "", "manual", "",
                       confirmed, privacy, suppressed)


def row(_id="1", **kw):
    base = {"achievement_id": _id, "domain": "learning", "item": "A", "title": "t", "level": "1", "date": "2024-01",
            "together": "false", "memory": "", "photo": "", "source": "", "origin": "manual", "confidence": "",
            "confirmed": "true", "privacy": "", "suppressed": "false"}
    base.update(kw)
    return ",".join(base[f] for f in ACH_FIELDS) + "\n"


def write_ach(tmp_path, rows, name="achievements.csv", encoding="utf-8", newline="\n", header=HEADER):
    p = tmp_path / name
    text = (header + "".join(rows)).replace("\r\n", "\n").replace("\n", newline)
    p.write_bytes(text.encode(encoding))
    return p
