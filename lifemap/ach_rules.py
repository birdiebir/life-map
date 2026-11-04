r"""候選去雜訊與項目對應規則。

- config\ach_rules.json（通用，進 git）＋ private\achievement_rules.json（個人，不進 git）。
- list 欄位（drop_title_patterns、signals、apply_to_origins、item_rules）：private 排前面、優先命中；
  純量欄位（min_title_chars、require_signal）：private 覆蓋。
- noise 只套用在 apply_to_origins 的候選；signal 比對 title＋evidence（不分大小寫，關鍵字可寫 regex）。
  太短的標題只有在標題本身不含 signal 時才擋（「碩士畢業」這種短而重要的不會被誤刪）。
- item_rules：依序比對，第一條命中就用；field＝title／file／any（預設 any）；可順便改 domain。
  選填 domains＝["learning", ...]：只套用到這些領域的候選（比對的是規則套用前的候選領域），沒寫就套用到全部。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_LINE_SUFFIX = re.compile(r":\d+$")


def _read(path: Path | None) -> dict:
    if path is None or not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _uniq(items: list) -> list:
    out, seen = [], set()
    for x in items:
        k = json.dumps(x, sort_keys=True, ensure_ascii=False)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def load_rules(config_path: Path, private_path: Path | None = None) -> dict:
    base, priv = _read(config_path), _read(private_path)
    bn, pn = base.get("noise") or {}, priv.get("noise") or {}
    noise = dict(bn)
    for k, v in pn.items():
        if isinstance(v, list):
            noise[k] = _uniq(list(v) + list(bn.get(k) or []))
        else:
            noise[k] = v
    noise.setdefault("apply_to_origins", [])
    noise.setdefault("min_title_chars", 0)
    noise.setdefault("drop_title_patterns", [])
    noise.setdefault("require_signal", False)
    noise.setdefault("signals", [])
    return {"noise": noise,
            "item_rules": list(priv.get("item_rules") or []) + list(base.get("item_rules") or [])}


def _file_of(source: str) -> str:
    s = _LINE_SUFFIX.sub("", source or "")
    return re.split(r"[\\/]", s)[-1]


def _has_signal(text: str, signals: list[str]) -> bool:
    return any(re.search(s, text, re.IGNORECASE) for s in signals)  # 關鍵字也可以寫成 regex


def _noise_reason(r: dict, noise: dict) -> str | None:
    if r.get("origin") not in noise["apply_to_origins"]:
        return None
    title = r.get("title", "")
    for p in noise["drop_title_patterns"]:
        if re.search(p, title):
            return f"pattern:{p}"
    sig = noise["signals"]
    if len(title) < noise["min_title_chars"] and not _has_signal(title, sig):
        return "too_short"
    if noise["require_signal"] and not _has_signal(title + " " + r.get("evidence", ""), sig):
        return "no_signal"
    return None


def _map_item(r: dict, item_rules: list[dict]) -> dict:
    title, fname = r.get("title", ""), _file_of(r.get("source", ""))
    for rule in item_rules:
        if rule.get("domains") and r.get("domain") not in rule["domains"]:
            continue  # 規則只套用在指定領域的候選
        field = rule.get("field", "any")
        texts = {"title": [title], "file": [fname]}.get(field, [title, fname])
        if any(re.search(rule["pattern"], t) for t in texts):
            r = {**r, "item": rule["item"]}
            if rule.get("domain"):
                r["domain"] = rule["domain"]
            return r
    return r


def apply_rules(rows: list[dict], rules: dict) -> tuple[list[dict], dict[str, int]]:
    kept, dropped = [], {}
    for r in rows:
        why = _noise_reason(r, rules["noise"])
        if why:
            dropped[why] = dropped.get(why, 0) + 1
            continue
        kept.append(_map_item(r, rules["item_rules"]))
    return kept, dropped
