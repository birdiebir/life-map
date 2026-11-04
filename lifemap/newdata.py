r"""偵測有沒有比上次匯入更新的旅程資料（Takeout zip）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

STATE = "import_state.json"


def load_state(data_dir: Path) -> dict:
    f = data_dir / STATE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def record_import(data_dir: Path, zips: list[Path], now: datetime | None = None) -> None:
    """匯入成功後呼叫：記下時間與當時各 zip 的修改時間。"""
    state = {"last_import": (now or datetime.now()).timestamp(),
             "files": {str(z): z.stat().st_mtime for z in zips if z.exists()}}
    (data_dir / STATE).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def candidates(sources: dict) -> list[Path]:
    """登記的 zip＋監看資料夾（watch_dirs）底下的 takeout*.zip。"""
    out = {Path(p) for p in sources.get("takeout_zips", [])}
    for d in sources.get("watch_dirs", []):
        d = Path(d)
        if d.is_dir():
            out.update(d.rglob("takeout*.zip"))
    return sorted(out)


def find_new(data_dir: Path) -> tuple[list[Path], str]:
    """回傳（新的檔案, 基準說明）。沒有匯入紀錄時以 pending.csv 修改時間當基準。"""
    sf = data_dir / "sources.json"
    sources = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    state = load_state(data_dir)
    known = state.get("files", {})
    if "last_import" in state:
        base, why = state["last_import"], "上次匯入"
    elif (data_dir / "pending.csv").exists():
        base, why = (data_dir / "pending.csv").stat().st_mtime, "pending.csv 修改時間（尚無匯入紀錄）"
    else:
        base, why = 0.0, "從未匯入"
    new = []
    for z in candidates(sources):
        if not z.exists():
            continue
        m = z.stat().st_mtime
        if str(z) in known:
            if m > known[str(z)]:
                new.append(z)
        elif m > base:
            new.append(z)
    return new, why
