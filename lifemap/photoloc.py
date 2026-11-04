r"""照片地點 → 觀察點（再走既有的 infer.build_candidates 變成足跡候選）。

兩種來源（路徑寫在 <資料夾>\sources.json 的 "photo_sources"，每項可加 "enabled": false 暫時關掉）：
- google_photos_dir：Google 相簿 Takeout 解壓後的資料夾，讀每張照片旁的 JSON（photoTakenTime／creationTime、
  geoDataExif／geoData 的 latitude／longitude；0,0 視為沒有）。不讀照片本身，也不複製照片（photo 欄留空，
  因為 Takeout 解壓資料夾之後會刪）。
- catalog_csv：雲端照片目錄 CSV（照片目錄.csv）。預設欄位 gps（"緯度,經度"）、date_taken（YYYY-MM-DD）、
  date_precision（只收 "day"，年或月精度的日期無法決定哪一天）；欄名可用 gps_col／date_col／precision_col 改。
座標只用來離線對地名，不寫進任何輸出檔（候選只有地點 ID 與日期）。
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

from .takeout import Observation, photo_observation

_FLOATS = re.compile(r"\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*")


def parse_gps(text: str) -> tuple[float, float] | None:
    m = _FLOATS.fullmatch(text or "")      # 整串都要是「緯度,經度」；歐式小數逗號（25,03,121,56）對不上就拒絕
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 1e-9 and abs(lon) < 1e-9):
        return None
    return lat, lon


def read_catalog_csv(cfg: dict) -> tuple[list[Observation], dict[str, int]]:
    gps_col, date_col = cfg.get("gps_col", "gps"), cfg.get("date_col", "date_taken")
    prec_col, prec_ok = cfg.get("precision_col", "date_precision"), cfg.get("precision", "day")
    stats = {"rows": 0, "no_gps": 0, "date_not_day": 0}
    out = []
    with Path(cfg["path"]).open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            stats["rows"] += 1
            gps = parse_gps(r.get(gps_col, ""))
            if gps is None:
                stats["no_gps"] += 1
                continue
            try:
                if r.get(prec_col, prec_ok) != prec_ok:
                    raise ValueError
                day = date.fromisoformat((r.get(date_col) or "")[:10])
            except ValueError:
                stats["date_not_day"] += 1
                continue
            out.append(Observation("photo", day, gps[0], gps[1], "", ""))
    return out, stats


def read_google_photos_dir(cfg: dict) -> tuple[list[Observation], dict[str, int]]:
    stats = {"rows": 0, "no_gps": 0, "date_not_day": 0}
    out = []
    for f in sorted(Path(cfg["path"]).rglob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not ("photoTakenTime" in d or "creationTime" in d):
            continue                                    # 相簿的 metadata.json 等不是照片
        stats["rows"] += 1
        o = photo_observation(d)
        if o is None:
            stats["no_gps"] += 1
            continue
        out.append(o)
    return out, stats


READERS = {"catalog_csv": read_catalog_csv, "google_photos_dir": read_google_photos_dir}


def read_sources(sources: list[dict]) -> tuple[list[Observation], list[tuple[str, dict]]]:
    """回傳（全部觀察點, [(來源名稱, 計數)]）。找不到路徑或不認得類型就丟 ValueError／FileNotFoundError。"""
    obs: list[Observation] = []
    report = []
    for s in sources:
        if s.get("enabled", True) is False:
            continue
        reader = READERS.get(s.get("type"))
        if reader is None:
            raise ValueError(f"不認得的照片來源類型：{s.get('type')}")
        if not Path(s.get("path", "")).exists():
            raise FileNotFoundError(f"找不到照片來源：{s.get('path')}")
        o, st = reader(s)
        obs += o
        report.append((s.get("label") or s.get("type"), {**st, "usable": len(o)}))
    return obs, report
