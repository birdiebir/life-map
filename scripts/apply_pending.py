r"""把 pending.csv 裡 decision=y 的候選足跡收進 visits.csv（照片從 zip 取出到 photos\），n 的留著不再冒出來。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.data import DataError  # noqa: E402
from lifemap.pending import apply_pending  # noqa: E402
from lifemap.reference import load_places  # noqa: E402


def main() -> int:
    data = paths.data_dir()
    try:
        r = apply_pending(data, load_places(paths.REFERENCE))
    except DataError as e:
        print(f"❌ {e}")
        return 1
    if not r["accepted"]:
        print("沒有 decision=y 的列，什麼都沒改。")
        return 0
    print(f"✅ 收進 {r['accepted']} 筆足跡、新增 {r.get('new_trips', 0)} 趟旅程；pending 還剩 {r['kept']} 筆")
    print("   接著跑 python scripts\\build_map.py 更新地圖")
    return 0


if __name__ == "__main__":
    sys.exit(main())
