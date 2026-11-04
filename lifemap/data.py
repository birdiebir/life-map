"""讀取與驗證個人足跡（visits.csv、trips.csv）。

CSV 可能被使用者用 Excel 編輯過，所以一律用 utf-8-sig 讀（容許 BOM）。
驗證錯誤一次全部列出（附 CSV 列號，表頭是第 1 列），方便一次改完。
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .reference import Place

DATE_RE = re.compile(r"^(\d{4}(-\d{2}(-\d{2})?)?)?$")
TRUE = {"true", "1", "yes", "y", "是", "t"}
FALSE = {"false", "0", "no", "n", "否", "f", ""}
VISIT_FIELDS = ["visit_id", "place_id", "date_start", "date_end", "level", "together", "trip_id",
                "memory", "photo", "source", "confidence", "confirmed"]
TRIP_FIELDS = ["trip_id", "name", "date_start", "date_end", "companions", "kind", "kb_link"]


class DataError(ValueError):
    pass


@dataclass(frozen=True)
class Visit:
    visit_id: str
    place_id: str
    date_start: str
    date_end: str
    level: int
    together: bool
    trip_id: str
    memory: str
    photo: str
    source: str
    confidence: str
    confirmed: bool


@dataclass(frozen=True)
class Trip:
    trip_id: str
    name: str
    date_start: str
    date_end: str
    companions: str
    kind: str
    kb_link: str


def _bool(value: str) -> bool | None:
    v = (value or "").strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    return None


def _read(path: Path, fields: list[str]) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [f for f in fields if f not in (reader.fieldnames or [])]
        if missing:
            raise DataError(f"{path.name} 缺少欄位：{', '.join(missing)}")
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]


def load_visits(path: Path, places: dict[str, Place]) -> list[Visit]:
    errors: list[str] = []
    visits: list[Visit] = []
    seen: set[str] = set()
    for i, r in enumerate(_read(path, VISIT_FIELDS), start=2):
        row_err = []
        if r["place_id"] not in places:
            row_err.append(f"地點 ID 不存在：{r['place_id']}")
        for f in ("date_start", "date_end"):
            if not DATE_RE.match(r[f]):
                row_err.append(f"{f} 格式要是 YYYY、YYYY-MM 或 YYYY-MM-DD：{r[f]}")
        try:
            level = int(r["level"])
            if not 0 <= level <= 5:
                row_err.append(f"等級要在 0～5：{r['level']}")
        except ValueError:
            level = 0
            row_err.append(f"等級不是整數：{r['level']}")
        together, confirmed = _bool(r["together"]), _bool(r["confirmed"])
        if together is None:
            row_err.append(f"together 要是 true／false：{r['together']}")
        if confirmed is None:
            row_err.append(f"confirmed 要是 true／false：{r['confirmed']}")
        if r["visit_id"] in seen:
            row_err.append(f"visit_id 重複：{r['visit_id']}")
        seen.add(r["visit_id"])
        if row_err:
            errors.append(f"第 {i} 列：" + "；".join(row_err))
            continue
        visits.append(Visit(r["visit_id"], r["place_id"], r["date_start"], r["date_end"], level, together,
                            r["trip_id"], r["memory"], r["photo"], r["source"], r["confidence"], confirmed))
    if errors:
        raise DataError(f"{path.name} 有 {len(errors)} 列要修正：\n" + "\n".join(errors))
    return visits


def load_trips(path: Path) -> dict[str, Trip]:
    if not path.exists():
        return {}
    return {r["trip_id"]: Trip(*(r[f] for f in TRIP_FIELDS)) for r in _read(path, TRIP_FIELDS)}


def load_crossings(path: Path) -> list[tuple[str, str]]:
    """出入境紀錄（border_crossings.csv：exit_date、entry_date，YYYY-MM-DD）→ [(出境, 入境)]；沒有檔案回傳空串列。"""
    if not path.exists():
        return []
    out, errors = [], []
    for i, r in enumerate(_read(path, ["exit_date", "entry_date"]), start=2):
        a, b = r["exit_date"], r["entry_date"]
        if not (re.match(r"^\d{4}-\d{2}-\d{2}$", a) and re.match(r"^\d{4}-\d{2}-\d{2}$", b)) or a > b:
            errors.append(f"第 {i} 列：日期要是 YYYY-MM-DD，而且出境不晚於入境：{a}～{b}")
            continue
        out.append((a, b))
    if errors:
        raise DataError(f"{path.name} 有 {len(errors)} 列要修正：\n" + "\n".join(errors))
    return out
