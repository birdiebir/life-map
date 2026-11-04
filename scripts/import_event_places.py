r"""有明確地名的事件 → 候選足跡：python scripts\import_event_places.py [--write] [--example]

讀 <資料夾>\sources.json 的 "place_event_sources"（相簿事件、信件訂房／機票確認、社群打卡；規則直接指定 place_id，
見 lifemap\place_events.py），結果「只新增」進 pending.csv（add_candidates：確認表原有的列一列都不動），
之後照原本的審核流程（decision 填 y／n → apply_pending.py）。預設試跑只印數字，--write 才寫。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.data import DataError, load_visits  # noqa: E402
from lifemap.pending import add_candidates  # noqa: E402
from lifemap.place_events import BATCH_LABEL, build_rows  # noqa: E402
from lifemap.reference import load_places  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="真的寫入 pending.csv（預設只試跑）")
    ap.add_argument("--example", action="store_true", help="用 private.example 的設定")
    ap.add_argument("--data-dir", help="資料夾（預設 private 資料夾）")
    args = ap.parse_args(argv)
    if args.write and args.example:
        ap.error("--write 不能搭配 --example（private.example 會進 git，不能寫入）")
    data = Path(args.data_dir) if args.data_dir else paths.EXAMPLE_DIR if args.example else paths.data_dir()
    src_file = data / "sources.json"
    sources = json.loads(src_file.read_text(encoding="utf-8")).get("place_event_sources", []) if src_file.exists() else []
    if not sources:
        print(f"❌ {src_file} 沒有 place_event_sources（範例見 private.example/sources.json）")
        return 1
    for s in sources:                                   # 相對路徑以設定檔資料夾為準
        for k in ("catalog", "context_csv"):
            if s.get(k) and not Path(s[k]).is_absolute():
                s[k] = str(data / s[k])
        if s.get("files"):
            s["files"] = [p if Path(p).is_absolute() else str(data / p) for p in s["files"]]
    places = load_places(paths.REFERENCE)
    try:
        existing = load_visits(data / "visits.csv", places)
        rows, report = build_rows(sources, places, existing)
    except (DataError, OSError, ValueError, KeyError) as e:
        print(f"❌ {type(e).__name__}：{e}")
        return 1
    for name, n, cov, skipped in report:
        if name == BATCH_LABEL:
            print(f"{name}（同地點、日期重疊）：只留一筆，去掉 {n} 筆")
            continue
        extra = "；略過 " + "、".join(f"{k} {v}" for k, v in skipped.items()) if skipped else ""
        print(f"來源 {name}：規則命中 {n} 筆，已有足跡涵蓋而略過 {cov} 筆{extra}")
    print(f"候選足跡共 {len(rows)} 筆")
    for r in rows[:50]:
        print(f"   - {r['date_start']}{'～' + r['date_end'] if r['date_end'] else ''}｜{r['place_name']}｜等級 {r['level']}｜{r['source']}｜信心 {r['confidence']}")
    if not args.write:
        print("（試跑，什麼都沒寫）")
        return 0
    added, dup = add_candidates(data / "pending.csv", rows)
    print(f"✅ 寫入 {data / 'pending.csv'}：新增 {added} 筆，確認表已有而略過 {dup} 筆（填 decision 欄 y／n）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
