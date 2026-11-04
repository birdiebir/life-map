r"""把 private\pending_achievements.csv 裡 decision 填 y 的候選收進 achievements.csv。

用法：python scripts\apply_achievements.py [--write] [--data-dir 資料夾]
預設 dry-run：在暫存副本上跑，只印會收幾筆、留幾筆，什麼都不寫；--write 才真的寫（呼叫 lifemap.ach_pending.apply_pending）。
decision 只能填 y／n 或留空，有別的值整批不動、結束碼 1。
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.ach_pending import apply_pending, sidecar_path  # noqa: E402
from lifemap.achievements import load_domains_for  # noqa: E402
from lifemap.data import DataError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="真的寫入（預設只試跑）")
    ap.add_argument("--data-dir", help="資料夾（預設 private\）")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else paths.PRIVATE_DIR
    pending = data_dir / "pending_achievements.csv"
    if not pending.exists():
        print(f"❌ 找不到 {pending}（先跑 import_achievements.py --write）")
        return 1
    try:
        domains = load_domains_for(data_dir)
        if args.write:
            ach = data_dir / "achievements.csv"
            bak = None
            if ach.exists():                       # 收進主檔前備份（加時間戳，不互相覆蓋）
                bak = ach.with_name(f"{ach.stem}.before_apply.{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv")
                shutil.copy(ach, bak)
            try:
                res = apply_pending(data_dir, domains)
            except DataError:
                if bak:
                    bak.unlink(missing_ok=True)     # 驗證失敗什麼都沒動，備份也不留
                raise
        else:  # dry-run：把會被動到的檔案複製到暫存資料夾再跑，確認驗證通過與筆數
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                for src in (pending, data_dir / "achievements.csv", sidecar_path(pending)):
                    if src.exists():
                        shutil.copy2(src, tmp / src.name)
                res = apply_pending(tmp, domains)
    except DataError as e:
        print(f"❌ {e}")
        return 1
    tag = "✅ 已寫入" if args.write else "（試跑，什麼都沒寫）"
    print(f"{tag} 收 {res['accepted']} 筆進 achievements.csv，留 {res['kept']} 筆在 pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
