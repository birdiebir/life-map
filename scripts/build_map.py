r"""產生人生成就地圖：python scripts\build_map.py [--include-unconfirmed]

輸出到 <資料夾>\output\life-map.html；加 --include-unconfirmed 時另存 life-map_預覽.html
（個人資料在 private\，沒有就用 private.example\）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設 cp950，印不出表情符號

import paths  # noqa: E402
from lifemap.build import build_payload, render_html  # noqa: E402
from lifemap.achievements import load_domains_for  # noqa: E402
from lifemap.data import DataError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-unconfirmed", action="store_true", help="連未確認的候選足跡一起畫")
    a = ap.parse_args()
    data = paths.data_dir()
    try:
        payload = build_payload(data, paths.REFERENCE, paths.config("levels"), paths.config("sets"),
                                paths.config("scoring"), include_unconfirmed=a.include_unconfirmed,
                                ach_domains=load_domains_for(data))
    except DataError as e:
        print(f"❌ {e}")
        return 1
    # 預覽（含未確認的候選）另存一份，正式地圖只放確認過的足跡
    out = data / "output" / ("life-map_預覽.html" if a.include_unconfirmed else "life-map.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(payload, paths.REFERENCE, paths.VENDOR), encoding="utf-8")
    s = payload["scores"]["me"]
    print(f"✅ {out}")
    print(f"   世界經驗值 {s['world']}、台灣經驗值 {s['taiwan']}；足跡 {len(payload['visits'])} 筆，"
          f"未確認 {payload['unconfirmed']} 筆")
    if a.include_unconfirmed:
        print(f"   人生成就預覽含待確認候選 {payload['ach']['pending_count']} 筆")
    return 0


if __name__ == "__main__":
    sys.exit(main())
