r"""有明確地名的事件 → 候選足跡（pending.csv 格式）：相簿事件、信件（訂房／機票確認）、社群打卡。

和 photoloc（座標 → 地名）不同，這裡的地點是設定檔裡「規則 → place_id」直接指定的（地點 ID 查 reference\ 的 CSV），
不做任何地名猜測。來源類型（寫在 <資料夾>\sources.json 的 "place_event_sources"）：
- album_places：照片目錄 CSV 的相簿／資料夾（group_albums），rules＝[{"match": regex, "place_id", "level": 可省略, "together": 可省略}]。
  日期取相簿內照片拍攝日範圍；沒有日期的相簿略過（足跡一定要有日期才有意義）。等級預設：範圍 2 天以上 4、單日 3。
- jsonl_places：JSONL（Gmail 萃取結果等），date_field／text_field／include／exclude 同 jsonl_events，rules 同上。
  日期是信件日期，不一定是到訪日，所以信心一律「低」。
origin 以 fb_／ig_ 開頭的來源（社群平台）信心強制「低」，source 欄寫 origin。其餘 source 欄寫 album／mail 等 origin（預設值）。
座標、照片路徑都不會出現在輸出裡。已有足跡涵蓋（同地點、等級不低於推定、日期重疊）的略過。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .ach_pending import NEVER_AUTO_PREFIXES
from .ach_sources_ext import group_albums, match_rule, parse_event_date
from .data import Visit
from .infer import _full_name, candidate_id, covered, date_range
from .reference import Place


def _row(place_id: str, ds: str, de: str, level: int, label: str, origin: str, conf: str, evidence: str,
         together: bool, places: dict[str, Place]) -> dict:
    return {"decision": "", "place_name": _full_name(place_id, places), "visit_id": candidate_id(place_id, ds, de),
            "place_id": place_id, "date_start": ds, "date_end": de if de != ds else "", "level": str(level),
            "together": "true" if together else "false", "trip_id": "", "memory": label[:60], "photo": "",
            "source": origin, "confidence": conf, "confirmed": "false", "evidence": evidence}


def _conf(origin: str, base: str) -> str:
    return "低" if origin.lower().startswith(NEVER_AUTO_PREFIXES) else base


def _place_ids(rule: dict, places: dict[str, Place]) -> list[str]:
    ids = rule.get("place_ids") or [rule["place_id"]]
    for pid in ids:
        if pid not in places:
            raise ValueError(f"規則的 place_id 不在地名庫：{pid}")
    return ids


def album_places(cfg: dict, places: dict[str, Place]) -> tuple[list[dict], dict[str, int]]:
    origin = cfg.get("origin", "album")
    groups, skipped = group_albums(cfg)
    rules = cfg.get("rules") or []
    out = []
    for g in groups:
        rule = match_rule(rules, g["key"])
        if rule is None:
            skipped["沒對到規則"] = skipped.get("沒對到規則", 0) + 1
            continue
        pids = _place_ids(rule, places)
        if not g["ds"]:
            skipped["沒有日期"] = skipped.get("沒有日期", 0) + 1
            continue
        ds, de = g["ds"], g["de"]
        multi = de != ds
        from_ctx = g["precision"] == "context"                # 照片沒有拍攝日，日期是資料夾背景表的推定
        level = int(rule.get("level", 4 if multi else 3))
        how = "資料夾背景表推定日期" if from_ctx else f"拍攝日 {ds}{'～' + de if multi else ''}"
        ev = f"{g['n']} 張照片，{how}；相簿：{g['key']}；來源：{cfg.get('label', origin)}"
        for pid in pids:
            out.append(_row(pid, ds, de, level, g["key"].rsplit("/", 1)[-1], origin,
                            "低" if from_ctx else _conf(origin, "中"), ev[:200], bool(rule.get("together")), places))
    return out, skipped


def jsonl_places(cfg: dict, places: dict[str, Place]) -> tuple[list[dict], dict[str, int]]:
    origin = cfg.get("origin", "mail")
    rules = cfg.get("rules") or []
    inc, exc = cfg.get("include") or [], cfg.get("exclude") or []
    tf, df = cfg.get("text_field", "subject"), cfg["date_field"]
    skipped: dict[str, int] = {}
    seen: set = set()
    out = []
    for f in cfg.get("files", []):
        if not Path(f).exists():
            continue
        with Path(f).open(encoding="utf-8-sig") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                text = str(rec.get(tf) or "")
                if (inc and not any(re.search(p, text) for p in inc)) or any(re.search(p, text) for p in exc):
                    continue
                rule = match_rule(rules, text)
                if rule is None:
                    continue
                pids = _place_ids(rule, places)
                d = parse_event_date(str(rec.get(df) or ""))
                if len(d) < 7:
                    skipped["日期無法辨識"] = skipped.get("日期無法辨識", 0) + 1
                    continue
                ev = f"{d}｜{text[:80]}（信件日期，不一定是到訪日）；來源：{cfg.get('label', origin)}"
                for pid in pids:
                    if (pid, d) in seen:
                        continue
                    seen.add((pid, d))
                    out.append(_row(pid, d, d, int(rule.get("level", 2)), text, origin,
                                    "低", ev[:200], bool(rule.get("together")), places))
    return out, skipped


BATCH_LABEL = "同一批新候選互相重複"
_CONF_RANK = {"高": 2, "中": 1, "低": 0}


def dedupe_batch(rows: list[dict]) -> tuple[list[dict], int]:
    """同一批新候選彼此重複（同地點、日期重疊）只留一筆：留等級高的，同級留信心高的，再同就留先出現的。
    保持原本的順序。回傳 (留下的, 被擋筆數)。"""
    order = sorted(range(len(rows)), key=lambda i: (-int(rows[i]["level"]), -_CONF_RANK.get(rows[i]["confidence"], 0), i))
    kept: dict[int, dict] = {}
    for i in order:
        r = rows[i]
        rng = date_range(r["date_start"], r["date_end"])
        clash = any(k["place_id"] == r["place_id"] and
                    (rng is None or date_range(k["date_start"], k["date_end"]) is None or
                     (rng[0] <= date_range(k["date_start"], k["date_end"])[1] and date_range(k["date_start"], k["date_end"])[0] <= rng[1]))
                    for k in kept.values())
        if not clash:
            kept[i] = r
    return [kept[i] for i in sorted(kept)], len(rows) - len(kept)


READERS = {"album_places": album_places, "jsonl_places": jsonl_places}


def build_rows(sources: list[dict], places: dict[str, Place], existing: list[Visit]):
    """回傳 (候選列, 報告 [(名稱, 產生數, 涵蓋略過數, skipped)])。"""
    rows: list[dict] = []
    report = []
    for s in sources:
        if s.get("enabled", True) is False:
            continue
        reader = READERS.get(s.get("type"))
        if reader is None:
            raise ValueError(f"不認得的足跡事件來源類型：{s.get('type')}")
        got, skipped = reader(s, places)
        keep = [r for r in got if not covered(existing, r["place_id"], int(r["level"]), r["date_start"], r["date_end"])]
        report.append((s.get("label") or s["type"], len(got), len(got) - len(keep), skipped))
        rows += keep
    seen, uniq = set(), []
    for r in rows:
        if r["visit_id"] not in seen:
            seen.add(r["visit_id"])
            uniq.append(r)
    out, n_batch = dedupe_batch(uniq)
    if n_batch:
        report.append((BATCH_LABEL, n_batch, 0, {}))
    return out, report
