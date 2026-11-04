r"""成就掃描（給 routine 每月呼叫）：唯讀跑一次候選匯入的試跑，找出確認表裡還沒有的新候選。

流程與 scripts\import_achievements.py 相同（來源 → 去雜訊 → 跨來源去重複 → 併進旅程），最後在暫存副本上
跑 merge_pending，新候選＝合併後出現、但原本確認表與 achievements.csv 都沒有的 ID。尚未決定的舊列標題改字換 ID 會被
重新連結而不算新；已決定的舊列或已收進主檔的換 ID 不會重新連結，仍算新候選（匯入後由 auto_decide 比對標註「疑似重複」，不自動決定）。不寫任何正式檔案；掃描日期另外記在 <資料夾>\achievement_scan_state.json。
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

from .ach_pending import merge_pending, sidecar_path
from .ach_rules import apply_rules, load_rules
from .ach_sources import absorb_trip_duplicates, build_sources, dedupe_across, drop_covered_by_main
from .achievements import load_achievements, load_domains_for
from .pending import read_rows

STATE = "achievement_scan_state.json"
DEFAULT_DAYS = 30


def last_scan(data_dir: Path) -> date | None:
    f = data_dir / STATE
    if not f.exists():
        return None
    try:
        return date.fromisoformat(json.loads(f.read_text(encoding="utf-8")).get("last_scan", ""))
    except (ValueError, AttributeError, TypeError):      # 壞檔、內容不是 dict 都當成沒有紀錄
        return None


def record_scan(data_dir: Path, today: date) -> None:
    (data_dir / STATE).write_text(json.dumps({"last_scan": today.isoformat()}, ensure_ascii=False), encoding="utf-8")


def is_due(data_dir: Path, today: date, days: int = DEFAULT_DAYS) -> tuple[bool, date | None]:
    last = last_scan(data_dir)
    return (last is None or (today - last).days >= days), last


def gather(base: Path, config_dir: Path) -> list[dict]:
    """所有來源的候選（已去雜訊、去重複、併進旅程），不寫檔。"""
    cfg = json.loads((base / "achievement_sources.json").read_text(encoding="utf-8-sig"))
    sources = build_sources(cfg, base_dir=base)
    rows: list[dict] = []
    spans: dict[str, tuple[str, str]] = {}
    for s in sources:
        rows += s.candidates()
        spans.update(getattr(s, "spans", {}))
    rules = load_rules(config_dir / "ach_rules.json", base / "achievement_rules.json")
    kept, _ = apply_rules(rows, rules)
    rows = dedupe_across(kept)
    absorb = sorted({i for s in sources if hasattr(s, "absorb_items") for i in s.absorb_items})
    rows, _ = absorb_trip_duplicates(rows, absorb, spans)
    ach_main = base / "achievements.csv"
    rows, _ = drop_covered_by_main(rows, read_rows(ach_main) if ach_main.exists() else [])
    return rows


def find_new(base: Path, config_dir: Path) -> tuple[list[dict], int]:
    """回傳（新候選, 候選總數）。"""
    rows = gather(base, config_dir)
    domains = load_domains_for(base)
    ach_path = base / "achievements.csv"
    existing = {a.achievement_id for a in load_achievements(ach_path, domains)} if ach_path.exists() else set()
    pending = base / "pending_achievements.csv"
    old_ids = {r["achievement_id"] for r in read_rows(pending)}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / pending.name
        if pending.exists():
            shutil.copy2(pending, tmp)
            if sidecar_path(pending).exists():
                shutil.copy2(sidecar_path(pending), sidecar_path(tmp))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            merged = merge_pending(tmp, rows, existing)
    new = [r for r in merged if r["achievement_id"] not in old_ids]
    return new, len(rows)
