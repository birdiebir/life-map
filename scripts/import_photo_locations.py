r"""照片地點 → 候選足跡：python scripts\import_photo_locations.py [--write] [--example]

讀 <資料夾>\sources.json 的 "photo_sources"（Google 相簿 Takeout 解壓資料夾、雲端照片目錄 CSV），依座標離線對到
既有地點庫（國家／城市／台灣縣市鄉鎮），同一地點同一天合併，已在 visits.csv 的不重複產生，結果「只新增」進 pending.csv
（沿用 import_takeout 的候選格式與審核流程：decision 填 y／n → apply_pending.py）。預設試跑只印數字，--write 才寫。
候選的 evidence 結尾標「照片來源：…」。座標不會寫進任何檔案。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.data import DataError, load_crossings, load_visits  # noqa: E402
from lifemap.geo import Locator  # noqa: E402
from lifemap.infer import build_candidates  # noqa: E402
from lifemap.pending import add_candidates  # noqa: E402
from lifemap.photoloc import read_sources  # noqa: E402
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
    sources = json.loads(src_file.read_text(encoding="utf-8")).get("photo_sources", []) if src_file.exists() else []
    if not sources:
        print(f"❌ {src_file} 沒有 photo_sources（範例見 private.example/sources.json）")
        return 1
    try:
        obs, report = read_sources(sources)
    except (OSError, ValueError) as e:
        print(f"❌ {e}")
        return 1
    for name, st in report:
        print(f"來源 {name}：讀 {st['rows']} 筆，沒有座標 {st['no_gps']}、日期不到日精度 {st['date_not_day']} → 可用 {st['usable']} 筆")
    label = "、".join(n for n, _ in report) or "照片"

    places = load_places(paths.REFERENCE)
    cfg = paths.config("import")
    try:
        existing = load_visits(data / "visits.csv", places)
        crossings = load_crossings(data / "border_crossings.csv")
    except DataError as e:
        print(f"❌ {e}")
        return 1
    rows, stats = build_candidates(obs, Locator(paths.REFERENCE, places, cfg), places, existing, cfg["trip_gap_days"],
                                   {k: v for k, v in cfg.get("rules", {}).items() if k != "說明"}, crossings)
    for r in rows:
        r["evidence"] += f"；照片來源：{label}"
    print(f"觀察點 {stats['observations']}（無法定位 {stats['unlocated']}）→ 候選 {stats['candidates']} 筆，"
          f"已有足跡涵蓋而略過 {stats['covered']} 筆")
    if not args.write:
        print("（試跑，什麼都沒寫）")
        return 0
    added, dup = add_candidates(data / "pending.csv", rows)
    print(f"✅ 寫入 {data / 'pending.csv'}：新增 {added} 筆，確認表已有而略過 {dup} 筆（填 decision 欄 y／n）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
