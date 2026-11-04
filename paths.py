r"""程式與個人資料的分界。

個人足跡（visits.csv、trips.csv、時間軸原始檔、產出的地圖）一律放在專案內的 private\（不進 git）。
別人要用這個專案：把 private.example\ 複製成 private\，換成自己的足跡即可。
也可以在 .env 用 LIFEMAP_PRIVATE_DIR 指到別的位置。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "reference"
CONFIG = ROOT / "config"
VENDOR = ROOT / "vendor"
EXAMPLE_DIR = ROOT / "private.example"


def _read_env() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = {**_read_env(), **os.environ}
PRIVATE_DIR = Path(ENV.get("LIFEMAP_PRIVATE_DIR") or ROOT / "private")


def data_dir() -> Path:
    """有 private\\visits.csv 就用個人資料，沒有就退回範例資料並提醒。"""
    if (PRIVATE_DIR / "visits.csv").exists():
        return PRIVATE_DIR
    print(f"⚠️ 找不到個人足跡，改用範例資料：{EXAMPLE_DIR}")
    return EXAMPLE_DIR


def config(name: str) -> dict | list:
    return json.loads((CONFIG / f"{name}.json").read_text(encoding="utf-8"))
