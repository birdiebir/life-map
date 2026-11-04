r"""成就掃描（給 routine 每月呼叫）：python scripts\check_achievements.py [--force] [--example]

唯讀：跑一次候選匯入的試跑，輸出一行。結束碼 0＝沒有新候選（或未滿 30 天跳過）、10＝有新候選、1＝出錯。
頻率：上次掃描日記在 private\achievement_scan_state.json（只有掃完沒有新候選才記，所以有新候選但還沒匯入前會一直提醒），
未滿 30 天直接跳過（--force 無視）。
有新候選時，後續流程：import_achievements.py --write → Opus 判等級與把握度 → apply_judgments.py --auto-decide --write
→ apply_achievements.py --write → build_map.py → sync_kb.py（見 README「成就候選的日常流程」）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.ach_scan import DEFAULT_DAYS, find_new, is_due, record_scan  # noqa: E402
from lifemap.data import DataError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="不管上次掃描日期，直接掃")
    ap.add_argument("--example", action="store_true", help="用 private.example（不記錄掃描日）")
    ap.add_argument("--data-dir", help="資料夾（預設 private\）")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"掃描間隔天數（預設 {DEFAULT_DAYS}）")
    args = ap.parse_args(argv)
    base = paths.EXAMPLE_DIR if args.example else (Path(args.data_dir) if args.data_dir else paths.PRIVATE_DIR)
    today = date.today()
    if not (base / "achievement_sources.json").exists():
        print(f"life-map 成就：找不到 {base / 'achievement_sources.json'}")
        return 1
    due, last = is_due(base, today, args.days)
    if not due and not args.force:
        print(f"life-map 成就：上次掃描 {last.isoformat()}，未滿 {args.days} 天，跳過")
        return 0
    try:
        new, total = find_new(base, paths.CONFIG)
    except (DataError, OSError, KeyError, ValueError) as e:
        print(f"life-map 成就：掃描失敗（{type(e).__name__}：{e}）")
        return 1
    if not new:
        if not args.example:
            record_scan(base, today)          # 有新候選時不記：匯入進確認表之前，下次還會再提醒
        print(f"life-map 成就：掃描 {total} 筆候選，沒有新的")
        return 0
    items: dict[str, int] = {}
    for r in new:
        k = f"{r['domain']}／{r['item']}"
        items[k] = items.get(k, 0) + 1
    detail = "、".join(f"{k} {n}" for k, n in sorted(items.items(), key=lambda kv: -kv[1]))
    print(f"life-map 成就：有 {len(new)} 筆新候選（{detail}），請跑 import_achievements.py --write 後判等級與把握度")
    return 10


if __name__ == "__main__":
    sys.exit(main())
