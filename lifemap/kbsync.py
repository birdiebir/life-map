r"""把 life-map 的收集進度同步到 KB 踩點表（只改 marker 之間的自動區塊）。"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
from pathlib import Path

from .data import DataError


def load_config(config_dir: Path, private_dir: Path) -> dict:
    r"""config\kb_sync.json 為底，private\kb_sync.json 同名鍵蓋過；缺 kb_root 或 note 就報錯。"""
    def _read(f: Path) -> dict:
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise DataError(f"讀不了 {f.name}（{f}）：{e}") from None
        if not isinstance(d, dict):
            raise DataError(f"{f.name}（{f}）格式要是 JSON 物件")
        return d

    cfg = _read(Path(config_dir) / "kb_sync.json")
    pf = Path(private_dir) / "kb_sync.json"
    if pf.exists():
        cfg.update(_read(pf))
    missing = [k for k in ("kb_root", "note") if not cfg.get(k)]
    if missing:
        raise DataError(f"KB 同步設定缺少 {'、'.join(missing)}：請把 private.example\\kb_sync.json "
                        f"複製到 private\\ 並改成自己的路徑（找的位置：{pf}）")
    return cfg


def render_block(payload: dict, places_names: dict[str, str], cfg: dict) -> str:
    """產生 marker 之間的內容（不含 marker 本身）。不放時間戳，數字沒變就不會有差異。"""
    sets = {s["id"]: s for s in payload["sets"]["me"]}
    lines = [cfg["heading"], "",
             r"> 由 life-map 的 `scripts\sync_kb.py` 產生，請勿手改這個區塊（手寫內容放區塊外）。「去過」＝等級 2 以上，轉機、路過不算。",
             "", "| 項目 | 去過 | 總數 |", "|---|---|---|"]
    for sid in cfg["set_ids"]:
        s = sets.get(sid)
        if s:
            lines.append(f"| {s['name']} | {s['done']} | {s['total']} |")
    # payload 的 sets 不含成員清單，國家名單從等級表算（等級 >= minLevel 的國家／地區）
    pl = payload["places"]
    names = sorted(places_names.get(pid, pid) for pid, lv in payload["lv"]["me"].items()
                   if lv >= payload["minLevel"] and pl.get(pid, {}).get("k") == "country")
    if names:
        lines += ["", "去過的國家／地區：" + "、".join(names)]
    sc = payload["scores"]["me"]
    lines += ["", f"經驗值：世界 {sc['world']}、台灣 {sc['taiwan']}；足跡 {len(payload['visits'])} 筆，待確認 {payload['unconfirmed']} 筆。"]
    return "\n".join(lines)


def _span(text: str, cfg: dict) -> tuple[int, int] | None:
    a, b = text.find(cfg["start_marker"]), text.find(cfg["end_marker"])
    if a == -1 or b == -1 or b < a:
        return None
    return a, b + len(cfg["end_marker"])


def current_block(text: str, cfg: dict) -> str | None:
    sp = _span(text, cfg)
    if not sp:
        return None
    return text[sp[0] + len(cfg["start_marker"]):sp[1] - len(cfg["end_marker"])].strip("\n")


def apply_block(text: str, block: str, cfg: dict) -> str:
    full = f"{cfg['start_marker']}\n{block}\n{cfg['end_marker']}"
    sp = _span(text, cfg)
    if sp:
        return text[:sp[0]] + full + text[sp[1]:]
    anchor = cfg.get("insert_before_heading", "")
    i = text.find("\n" + anchor) if anchor else -1
    if i == -1:
        return text.rstrip("\n") + "\n\n" + full + "\n"
    return text[:i + 1] + full + "\n\n" + text[i + 1:]


def _numbers(block: str | None) -> dict[str, int]:
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"^\| (.+?) \| (\d+) \| \d+ \|$", block or "", re.M)}


def _names(block: str | None) -> set[str]:
    m = re.search(r"^去過的國家／地區：(.*)$", block or "", re.M)
    return set(m.group(1).split("、")) if m and m.group(1) else set()


def shrinks(old_block: str | None, new_block: str) -> list[str]:
    """舊區塊有、新區塊少了或變小的項目（代表有刪除，不是單純新增）。"""
    if old_block is None:
        return []
    on, nn = _numbers(old_block), _numbers(new_block)
    out = [f"{k} {v}→{nn.get(k, 0)}" for k, v in on.items() if nn.get(k, 0) < v]
    out += [f"國家少了 {n}" for n in sorted(_names(old_block) - _names(new_block))]
    return out


def diff_lines(old: str, new: str) -> list[str]:
    return list(difflib.unified_diff(old.splitlines(), new.splitlines(), "KB", "new", lineterm="", n=0))


def changed_count(diff: list[str]) -> int:
    return sum(1 for l in diff if l[:1] in "+-" and not l.startswith(("+++", "---")))


def git_commit_note(kb_root: Path, rel: str, message: str, trailer: str) -> str:
    """只 add 那一篇並 commit，回傳 commit 簡短雜湊。"""
    def run(*a):
        return subprocess.run(["git", "-C", str(kb_root), *a], check=True, capture_output=True, text=True,
                              encoding="utf-8").stdout.strip()
    run("add", "--", rel)
    run("commit", "-m", f"{message}\n\n{trailer}", "--only", "--", rel)
    return run("rev-parse", "--short", "HEAD")
