r"""把收集進度同步到 KB 踩點表：python scripts\sync_kb.py --dry-run | --apply

只改筆記裡 marker 之間的自動區塊（通用設定在 config\kb_sync.json，個人路徑在 private\kb_sync.json）。
--dry-run 只印差異；--apply 才寫入並 commit（只 add 那一篇）。
有「減少」的項目、或變動行數超過上限時拒絕 apply，要人看過再加 --force。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap import kbsync  # noqa: E402
from lifemap.build import build_payload  # noqa: E402
from lifemap.data import DataError  # noqa: E402
from lifemap.reference import load_places  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="有減少或大量變動時仍要寫入")
    ap.add_argument("--no-commit", action="store_true")
    a = ap.parse_args(argv)

    try:
        cfg = kbsync.load_config(paths.CONFIG, paths.PRIVATE_DIR)
    except DataError as e:
        print(f"❌ {e}")
        return 1
    note = Path(cfg["kb_root"]) / cfg["note"]
    if not note.exists():
        print(f"❌ 找不到 KB 筆記：{note}")
        return 1
    data = paths.data_dir()
    places = load_places(paths.REFERENCE)
    payload = build_payload(data, paths.REFERENCE, paths.config("levels"), paths.config("sets"),
                            paths.config("scoring"), places=places)
    block = kbsync.render_block(payload, {k: p.name for k, p in places.items()}, cfg)
    old = note.read_text(encoding="utf-8")
    new = kbsync.apply_block(old, block, cfg)
    if new == old:
        print("✅ KB 已是最新，沒有差異")
        return 0
    diff = kbsync.diff_lines(old, new)
    n = kbsync.changed_count(diff)
    old_block = kbsync.current_block(old, cfg)
    shr = kbsync.shrinks(old_block, block)
    print(f"差異 {n} 行（{'首次建立自動區塊' if old_block is None else '更新自動區塊'}）；減少項目 {len(shr)} 個")
    print("\n".join(diff))
    if a.dry_run:
        return 0
    if (shr or n > cfg["max_changed_lines"]) and not a.force:
        print(f"❌ 拒絕 apply：{'有減少項目 ' + '；'.join(shr) if shr else '變動行數超過上限'}。確認後加 --force")
        return 2
    note.write_text(new, encoding="utf-8")
    print(f"✅ 已寫入 {note}")
    if not a.no_commit:
        h = kbsync.git_commit_note(Path(cfg["kb_root"]), cfg["note"], cfg["commit_message"], cfg["commit_trailer"])
        print(f"✅ KB commit {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
