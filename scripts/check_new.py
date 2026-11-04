r"""有沒有新的旅程資料要匯入：python scripts\check_new.py

回報一行給 routine 用。結束碼 0＝沒有新資料、10＝有新資料（要跑 import_takeout.py）。
監看來源：private\sources.json 的 takeout_zips 與 watch_dirs（資料夾，找 takeout*.zip）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.newdata import find_new  # noqa: E402


def main() -> int:
    new, why = find_new(paths.data_dir())
    if not new:
        print(f"life-map：沒有比{why}更新的旅程資料")
        return 0
    print(f"life-map：有 {len(new)} 個比{why}更新的旅程資料（{'、'.join(z.name for z in new)}），"
          r"請跑 python scripts\import_takeout.py 後審 pending.csv")
    return 10


if __name__ == "__main__":
    sys.exit(main())
