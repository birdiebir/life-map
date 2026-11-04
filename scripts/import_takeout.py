r"""從 Google Takeout（地圖評論、地圖照片）產生候選足跡 → <資料夾>\pending.csv

zip 路徑寫在 <資料夾>\sources.json：{"takeout_zips": ["D:\\...\\takeout-....zip"]}
zip 只唯讀，不解壓縮。產生後用 Excel 開 pending.csv，在 decision 欄填 y／n，再跑 apply_pending.py。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.data import DataError, load_crossings, load_visits  # noqa: E402
from lifemap.geo import Locator  # noqa: E402
from lifemap.infer import build_candidates  # noqa: E402
from lifemap.newdata import record_import  # noqa: E402
from lifemap.pending import merge_pending  # noqa: E402
from lifemap.reference import load_places  # noqa: E402
from lifemap.takeout import read_takeout  # noqa: E402


def main() -> int:
    data = paths.data_dir()
    src_file = data / "sources.json"
    if not src_file.exists():
        print(f"❌ 找不到 {src_file}，請寫入 {{\"takeout_zips\": [\"zip 路徑\"]}}")
        return 1
    zips = [Path(p) for p in json.loads(src_file.read_text(encoding="utf-8")).get("takeout_zips", [])]
    missing = [str(z) for z in zips if not z.exists()]
    if missing:
        print("❌ 找不到 zip：" + "、".join(missing))
        return 1

    places = load_places(paths.REFERENCE)
    cfg = paths.config("import")
    try:
        existing = load_visits(data / "visits.csv", places)
        crossings = load_crossings(data / "border_crossings.csv")
    except DataError as e:
        print(f"❌ {e}")
        return 1
    obs = list({(o.source, o.ref, o.day, o.lat, o.lon): o for z in zips for o in read_takeout(z)}.values())
    rows, stats = build_candidates(obs, Locator(paths.REFERENCE, places, cfg), places, existing, cfg["trip_gap_days"],
                                   {k: v for k, v in cfg.get("rules", {}).items() if k != "說明"}, crossings)
    merged = merge_pending(data / "pending.csv", rows)
    record_import(data, zips)
    decided = sum(1 for r in merged if r.get("decision"))
    print(f"✅ {data / 'pending.csv'}")
    print(f"   觀察點 {stats['observations']}（無法定位 {stats['unlocated']}、沒有座標 {stats['no_coordinates']}）→ 候選 {stats['candidates']} 筆，"
          f"已有足跡涵蓋而略過 {stats['covered']} 筆；表內共 {len(merged)} 筆，已填決定 {decided} 筆")
    return 0


if __name__ == "__main__":
    sys.exit(main())
