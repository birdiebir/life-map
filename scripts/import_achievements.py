r"""從 private\achievement_sources.json 設定的來源產生成就候選。

預設 --dry-run：只印每個來源的候選數與前 3 筆標題，不寫任何檔案。
--write：合併進 private\pending_achievements.csv（已填的決定保留、n 的不再冒出、已收進 achievements.csv 的略過）。
--example：改用 private.example\ 的設定與假資料（試跑用）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.ach_pending import merge_pending  # noqa: E402
from lifemap.ach_rules import apply_rules, load_rules  # noqa: E402
from lifemap.ach_sources import absorb_trip_duplicates, build_sources, dedupe_across, drop_covered_by_main  # noqa: E402
from lifemap.achievements import load_achievements, load_domains_for  # noqa: E402
from lifemap.data import DataError  # noqa: E402
from lifemap.pending import read_rows  # noqa: E402


def filter_candidates(rows: list[dict], rules: dict) -> tuple[list[dict], dict[str, int], int]:
    """先去雜訊、再跨來源去重複（避免好的那筆被同標題的雜訊筆一起去掉）。回傳 (候選, 被擋原因計數, 去雜訊後筆數)。"""
    kept, dropped = apply_rules(rows, rules)
    return dedupe_across(kept), dropped, len(kept)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="真的寫入 pending_achievements.csv（預設只試跑）")
    ap.add_argument("--dry-run", action="store_true", help="只印候選數與前 3 筆標題（預設行為）")
    ap.add_argument("--example", action="store_true", help="用 private.example 的設定與假資料")
    args = ap.parse_args(argv)
    if args.write and args.dry_run:
        ap.error("--write 與 --dry-run 不能一起用")
    if args.write and args.example:
        ap.error("--write 不能搭配 --example（private.example 會進 git，不能寫入）")

    base = paths.EXAMPLE_DIR if args.example else paths.PRIVATE_DIR
    cfg_path = base / "achievement_sources.json"
    if not cfg_path.exists():
        print(f"❌ 找不到 {cfg_path}（可以從 private.example\\achievement_sources.json 複製後修改）")
        return 1
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    sources = build_sources(cfg, base_dir=base)

    all_rows: list[dict] = []
    spans: dict[str, tuple[str, str]] = {}
    for s in sources:
        try:
            rows = s.candidates()
        except (OSError, KeyError, ValueError) as e:
            print(f"❌ 來源 {s.name} 讀取失敗：{type(e).__name__}：{e}")
            return 1
        print(f"來源 {s.name}：{len(rows)} 筆候選")
        for r in rows[:3]:
            print(f"   - {r['date'] or '（無日期）'}｜{r['title']}")
        if getattr(s, "skipped", None):
            print("   略過的列：" + "、".join(f"{k} {n}" for k, n in s.skipped.items()))
        all_rows += rows
        spans.update(getattr(s, "spans", {}))

    n_raw = len(all_rows)
    rules = load_rules(paths.CONFIG / "ach_rules.json", base / "achievement_rules.json")
    all_rows, dropped, n_denoised = filter_candidates(all_rows, rules)
    print(f"\n原始 {n_raw} 筆 → 去雜訊後 {n_denoised} 筆 → 跨來源去重複後 {len(all_rows)} 筆")
    absorb = sorted({i for s in sources if hasattr(s, "absorb_items") for i in s.absorb_items})
    all_rows, n_absorbed = absorb_trip_duplicates(all_rows, absorb, spans)
    ach_main = base / "achievements.csv"
    all_rows, n_covered = drop_covered_by_main(all_rows, read_rows(ach_main) if ach_main.exists() else [])
    if n_covered:
        print(f"主檔已有同領域同項目、等級不低於候選的 {n_covered} 筆不產生候選")
    if absorb:
        print(f"併進旅程 {n_absorbed} 筆（旅程期間內的 {'、'.join(absorb)} 不另外出候選）")
    if dropped:
        print("被規則擋掉：")
        for why, n in sorted(dropped.items(), key=lambda kv: -kv[1]):
            print(f"   {n:4d}  {why}")
    items: dict[str, int] = {}
    for r in all_rows:
        key = f"{r['domain']}／{r['item']}"
        items[key] = items.get(key, 0) + 1
    print("各項目筆數：")
    for k, n in sorted(items.items(), key=lambda kv: -kv[1]):
        print(f"   {n:4d}  {k}")

    if not args.write:
        print(f"（試跑，什麼都沒寫）共 {len(all_rows)} 筆候選")
        return 0

    domains = load_domains_for(base)
    existing: set[str] = set()
    ach_path = base / "achievements.csv"
    if ach_path.exists():
        try:
            existing = {a.achievement_id for a in load_achievements(ach_path, domains)}
        except DataError as e:
            print(f"❌ {e}")
            return 1
    merged = merge_pending(base / "pending_achievements.csv", all_rows, existing)
    print(f"✅ 寫入 {base / 'pending_achievements.csv'}：共 {len(merged)} 筆（填 decision 欄 y／n）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
