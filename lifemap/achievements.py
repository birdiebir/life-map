r"""人生成就（第二階段）的資料模型與讀取。

- config\domains.json：領域、1～5 級定義、各級分數、套組、雷達、隱私等級。
- private\achievements.csv：成就主資料（utf-8-sig 讀，容許 Excel 的 BOM／CRLF；錯誤一次列出附列號）。
- private\achievement_suppress.json：整段「不再提起」規則。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .data import DATE_RE, DataError, _bool, _read

ACH_FIELDS = ["achievement_id", "domain", "item", "title", "level", "date", "together", "memory", "photo",
              "source", "origin", "confidence", "confirmed", "privacy", "suppressed"]


@dataclass(frozen=True)
class SetDef:
    id: str
    name: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class Domain:
    id: str
    name: str
    levels: dict
    scores: dict
    recommend: bool
    privacy: str
    sets: tuple[SetDef, ...]


@dataclass(frozen=True)
class Domains:
    by_id: dict
    top_n: int
    visited_min_level: int
    privacy_levels: tuple[str, ...]
    travel_kind: str = "country"


@dataclass(frozen=True)
class Achievement:
    achievement_id: str
    domain: str
    item: str
    title: str
    level: int
    date: str
    together: bool
    memory: str
    photo: str
    source: str
    origin: str
    confidence: str
    confirmed: bool
    privacy: str
    suppressed: bool


def load_domains(cfg: dict, extra_sets: dict | None = None) -> Domains:
    """extra_sets＝{領域: [{id,name,items}]}：同 id 取代通用套組、新 id 附加（個人清單放 private）。"""
    privacy_levels = tuple(cfg.get("privacy_levels") or ["local", "kb"])
    errors: list[str] = []
    by_id: dict[str, Domain] = {}
    for did, d in (cfg.get("domains") or {}).items():
        try:
            scores = {int(k): v for k, v in d["scores"].items()}
        except (KeyError, ValueError, AttributeError):
            errors.append(f"{did}：scores 要有 0～5 的分數表")
            continue
        if sorted(scores) != [0, 1, 2, 3, 4, 5]:
            errors.append(f"{did}：scores 要剛好有 0、1、2、3、4、5 六級")
            continue
        privacy = d.get("privacy", "local")
        if privacy not in privacy_levels:
            errors.append(f"{did}：預設隱私等級不存在：{privacy}")
            continue
        merged = {}
        bad_set = False
        for s in [*d.get("sets", []), *(extra_sets or {}).get(did, [])]:
            if not isinstance(s, dict) or not (s.get("id") and s.get("name") and isinstance(s.get("items"), list)):
                errors.append(f"{did}：套組缺 id／name／items：{s}")
                bad_set = True
                continue
            merged[s["id"]] = s  # 同 id 後者（個人）取代前者
        if bad_set:
            continue
        sets = tuple(SetDef(s["id"], s["name"], tuple(s["items"])) for s in merged.values())
        by_id[did] = Domain(did, d.get("name", did), {int(k): v for k, v in d.get("levels", {}).items()},
                            scores, bool(d.get("recommend", False)), privacy, sets)
    for did in (extra_sets or {}):
        if did not in (cfg.get("domains") or {}):
            errors.append(f"achievement_sets.json：領域不存在：{did}")
    if errors:
        raise DataError("domains.json 有問題：\n" + "\n".join(errors))
    return Domains(by_id, int((cfg.get("radar") or {}).get("top_n", 5)), int(cfg.get("visited_min_level", 1)),
                   privacy_levels, str((cfg.get("radar") or {}).get("travel_kind", "country")))


def load_domains_for(data_dir: Path, config_path: Path | None = None) -> Domains:
    """讀 config 的 domains.json ＋ data_dir 的 achievement_sets.json（沒有就略過）。所有呼叫端用這個。"""
    if config_path is None:
        from paths import CONFIG
        config_path = CONFIG / "domains.json"
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    sets_path = Path(data_dir) / "achievement_sets.json"
    extra = json.loads(sets_path.read_text(encoding="utf-8-sig")) if sets_path.exists() else None
    return load_domains(cfg, extra)


def load_achievements(path: Path, domains: Domains) -> list[Achievement]:
    errors: list[str] = []
    out: list[Achievement] = []
    seen: set[str] = set()
    for i, r in enumerate(_read(path, ACH_FIELDS), start=2):
        row_err = []
        if not r["achievement_id"]:
            row_err.append("achievement_id 必填")
        elif r["achievement_id"] in seen:
            row_err.append(f"achievement_id 重複：{r['achievement_id']}")
        seen.add(r["achievement_id"])
        dom = domains.by_id.get(r["domain"])
        if dom is None:
            row_err.append(f"領域不存在：{r['domain']}")
        for f in ("item", "title"):
            if not r[f]:
                row_err.append(f"{f} 必填")
        try:
            level = int(r["level"])
            if not 0 <= level <= 5:
                row_err.append(f"等級要在 0～5：{r['level']}")
        except ValueError:
            level = 0
            row_err.append(f"等級不是整數：{r['level']}")
        if not DATE_RE.match(r["date"]):
            row_err.append(f"date 格式要是 YYYY、YYYY-MM 或 YYYY-MM-DD：{r['date']}")
        flags = {}
        for f in ("together", "confirmed", "suppressed"):
            flags[f] = _bool(r[f])
            if flags[f] is None:
                row_err.append(f"{f} 要是 true／false：{r[f]}")
        privacy = r["privacy"] or (dom.privacy if dom else "")
        if privacy and privacy not in domains.privacy_levels:
            row_err.append(f"隱私等級不存在：{privacy}")
        if row_err:
            errors.append(f"第 {i} 列：" + "；".join(row_err))
            continue
        out.append(Achievement(r["achievement_id"], r["domain"], r["item"], r["title"], level, r["date"],
                               flags["together"], r["memory"], r["photo"], r["source"], r["origin"],
                               r["confidence"], flags["confirmed"], privacy, flags["suppressed"]))
    if errors:
        raise DataError(f"{path.name} 有 {len(errors)} 列要修正：\n" + "\n".join(errors))
    return out


def load_suppress_rules(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rules = json.loads(path.read_text(encoding="utf-8-sig"))
    errors = []
    for i, r in enumerate(rules, start=1):
        for k in ("date_from", "date_to"):
            if r.get(k) and not DATE_RE.match(r[k]):
                errors.append(f"第 {i} 條規則：{k} 格式要是 YYYY、YYYY-MM 或 YYYY-MM-DD：{r[k]}")
        unknown = set(r) - {"domain", "item", "date_from", "date_to"}
        if unknown:
            errors.append(f"第 {i} 條規則：不認得的欄位 {', '.join(sorted(unknown))}")
    if errors:
        raise DataError(f"{path.name} 有問題：\n" + "\n".join(errors))
    return rules


def _bounds(d: str) -> tuple[str, str]:
    """部分日期展開成區間（YYYY → 該年第一天～最後一天），供重疊判斷。"""
    parts = d.split("-")
    if len(parts) == 1:
        return f"{d}-01-01", f"{d}-12-31"
    if len(parts) == 2:
        return f"{d}-01", f"{d}-31"
    return d, d


def is_suppressed(a: Achievement, rules: list[dict]) -> bool:
    if a.suppressed:
        return True
    for r in rules:
        if r.get("domain") and r["domain"] != a.domain:
            continue
        if r.get("item") and r["item"] != a.item:
            continue
        if r.get("date_from") or r.get("date_to"):
            if not a.date:
                continue
            lo, hi = _bounds(a.date)
            if r.get("date_from") and hi < _bounds(r["date_from"])[0]:
                continue
            if r.get("date_to") and lo > _bounds(r["date_to"])[1]:
                continue
        return True
    return False
