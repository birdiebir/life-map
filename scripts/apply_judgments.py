r"""把 Opus 的等級判斷寫進 private\pending_achievements.csv（level／suggest／reason）。

用法：python scripts\apply_judgments.py [judgments.json] [--auto-decide] [--default-certainty 高] [--write] [--data-dir 資料夾]
judgments.json：[{"achievement_id", "level"(0～5), "suggest"("y"/"n"), "reason", 選填 "certainty"("高"/"低"), "title","item","domain","confidence"}]
預設 dry-run（只驗證並印摘要）；--write 才寫。已填 decision 的列不覆蓋；絕不碰 achievements.csv。
--auto-decide：把握度「高」的列照 suggest 自動填 decision（y→y、n→n，auto 欄記下；寫入前備份 .before_auto.<時間戳>.csv），
低把握度的留空給使用者；可以不給 judgments.json 單獨使用。--default-certainty：把握度空白的列視為這個值（套用既有批次時用）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.ach_pending import CERTAINTY, apply_judgments, auto_decide  # noqa: E402
from lifemap.achievements import load_domains_for  # noqa: E402
from lifemap.data import DataError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("judgments", nargs="?", help="判斷檔 JSON（用 --auto-decide 時可省略）")
    ap.add_argument("--auto-decide", action="store_true", help="高把握度的列照 suggest 自動填 decision")
    ap.add_argument("--default-certainty", choices=CERTAINTY, help="把握度空白的列視為這個值")
    ap.add_argument("--write", action="store_true", help="真的寫入（預設只驗證）")
    ap.add_argument("--data-dir", help="資料夾（預設 private\\）")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else paths.PRIVATE_DIR
    pending = data_dir / "pending_achievements.csv"
    if not pending.exists():
        print(f"❌ 找不到 {pending}（先跑 import_achievements.py --write）")
        return 1
    if not args.judgments and not args.auto_decide:
        ap.error("要給判斷檔，或加 --auto-decide")
    judgments = json.loads(Path(args.judgments).read_text(encoding="utf-8-sig")) if args.judgments else []
    tag = "✅ 已寫入" if args.write else "（試跑，什麼都沒寫）"
    try:
        domains = load_domains_for(data_dir)
        with tempfile.TemporaryDirectory() as td:         # 試跑與實跑都先在暫存副本上驗證，通過才動正本
            tmp = Path(td) / pending.name
            shutil.copy2(pending, tmp)
            res = apply_judgments(tmp, judgments, domains) if judgments else {"applied": 0, "skipped_decided": 0}
            auto = auto_decide(tmp, args.default_certainty or "") if args.auto_decide else None
            if args.write:
                if args.auto_decide:                          # 自動決定前留一份備份
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")      # 加時間戳，多次執行不互相覆蓋
                    shutil.copy(pending, pending.with_name(f"{pending.stem}.before_auto.{stamp}.csv"))
                if judgments:
                    apply_judgments(pending, judgments, domains)
                if args.auto_decide:
                    auto = auto_decide(pending, args.default_certainty or "")
    except DataError as e:
        print(f"❌ {e}")
        return 1
    if judgments:
        print(f"{tag} 套用 {res['applied']} 筆，略過已填 decision 的 {res['skipped_decided']} 筆")
    if auto is not None:
        print(f"{tag} 自動決定：收 {auto['auto_y']}、不收 {auto['auto_n']}；低把握度（要問使用者）{auto['ask_user']}"
              f"（其中疑似重複 {auto['suspected_dup']}）；沒有建議 {auto['no_suggest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
