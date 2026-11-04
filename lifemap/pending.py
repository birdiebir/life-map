r"""候選足跡確認表 pending.csv：使用者在 decision 欄填 y（收）或 n（不收），也可以直接改 level、together、memory。

- 重新匯入時，已經填過的決定和修改會保留（用 visit_id 對，同一地點同一段日期 ID 固定）。
- apply：y 的移到 visits.csv（confirmed=true），照片從 zip 取出到 private\photos\；n 的留在表裡，之後不會再冒出來。
- CSV 一律寫成 UTF-8 BOM，Excel 開中文才不會亂碼。
"""
from __future__ import annotations

import csv
import zipfile
from pathlib import Path

from .data import TRIP_FIELDS, VISIT_FIELDS, DataError, _bool, load_trips, load_visits
from .reference import Place

PENDING_FIELDS = ["decision", "place_name", *VISIT_FIELDS, "evidence"]
KEEP_ON_REIMPORT = ["decision", "level", "together", "memory", "trip_id"]
YES = {"y", "yes", "是", "收", "1", "true"}
NO = {"n", "no", "否", "不收", "0", "false"}


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(fh)]


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


TAKEOUT_SOURCES = {"review", "photo", "review+photo"}
PHOTO_TAG = "照片來源："


def _keep_unproduced(o: dict) -> bool:
    """takeout 匯入這次沒產生的舊列要不要留：填過任何決定（y／n）的留；不是 Takeout 產生的（照片地點、信件、相簿、
    社群來源，source 不在 TAKEOUT_SOURCES，或 evidence 標著「照片來源：」）也留，不然下次匯入 Takeout 會把它們洗掉。"""
    if o.get("decision", "").strip():
        return True
    if PHOTO_TAG in o.get("evidence", ""):
        return True
    return o.get("source", "") not in TAKEOUT_SOURCES


def merge_pending(path: Path, new_rows: list[dict]) -> list[dict]:
    """新候選＋舊表：保留舊表的決定與修改；舊表裡 n 的列就算這次沒產生也留著。"""
    old = {r["visit_id"]: r for r in read_rows(path)}
    merged = []
    for r in new_rows:
        o = old.pop(r["visit_id"], None)
        if o and o.get("decision"):  # 使用者填過決定才保留舊表的值；沒動過的用最新推定
            r = {**r, **{k: o[k] for k in KEEP_ON_REIMPORT if k in o}}
        merged.append(r)
    merged += [o for o in old.values() if _keep_unproduced(o)]
    merged.sort(key=lambda r: (r["date_start"], r["place_id"]))
    write_rows(path, PENDING_FIELDS, merged)
    return merged


def add_candidates(path: Path, new_rows: list[dict]) -> tuple[int, int]:
    """只新增：確認表裡已經有的 visit_id（不論有沒有決定）不動，也不丟掉任何舊列。回傳（新增, 已有而略過）。"""
    old = read_rows(path)
    have = {r["visit_id"] for r in old}
    add = [r for r in new_rows if r["visit_id"] not in have]
    if add:
        merged = sorted(old + add, key=lambda r: (r.get("date_start", ""), r.get("place_id", "")))
        write_rows(path, PENDING_FIELDS, merged)
    return len(add), len(new_rows) - len(add)


def _extract_photo(ref: str, photo_dir: Path) -> str:
    """zip:<zip 路徑>!<檔名> → 取出到 photos\，回傳相對路徑；只取檔名，避免路徑穿越。"""
    if not ref.startswith("zip:"):
        return ref
    zip_path, member = ref[4:].rsplit("!", 1)
    target = photo_dir / Path(member).name
    if not target.exists():
        photo_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            target.write_bytes(z.read(member))
    return f"photos/{target.name}"


def apply_pending(data_dir: Path, places: dict[str, Place]) -> dict:
    pending_path = data_dir / "pending.csv"
    rows = read_rows(pending_path)
    bad = [f"{r['visit_id']}：{r['decision']}" for r in rows
           if r.get("decision", "").lower() not in YES | NO | {""}]
    if bad:
        raise DataError("decision 只能填 y／n 或留空：" + "、".join(bad))
    accept = [r for r in rows if r.get("decision", "").lower() in YES]
    if not accept:
        return {"accepted": 0, "kept": len(rows)}

    visits_path = data_dir / "visits.csv"
    existing = load_visits(visits_path, places)
    next_id = max((int(v.visit_id) for v in existing if v.visit_id.isdigit()), default=0) + 1
    with visits_path.open(encoding="utf-8-sig", newline="") as fh:
        current = [dict(r) for r in csv.DictReader(fh)]
    for r in accept:
        current.append({**{k: r.get(k, "") for k in VISIT_FIELDS}, "visit_id": str(next_id), "confirmed": "true",
                        "together": "true" if _bool(r.get("together", "")) else "false",
                        "photo": _extract_photo(r.get("photo", ""), data_dir / "photos")})
        next_id += 1

    tmp = visits_path.with_suffix(".tmp")
    write_rows(tmp, VISIT_FIELDS, current)
    load_visits(tmp, places)  # 寫入前再驗一次，有錯就不覆蓋
    tmp.replace(visits_path)

    trips = load_trips(data_dir / "trips.csv")
    new_trips = []
    for tid in sorted({r["trip_id"] for r in accept if r["trip_id"].startswith("A-")} - set(trips)):
        _, iso3, ym = tid.split("-")
        country = places.get(f"C-{iso3}")
        new_trips.append({"trip_id": tid, "name": f"{country.name if country else iso3} {ym[:4]}-{ym[4:]}（自動）",
                          "date_start": f"{ym[:4]}-{ym[4:]}", "date_end": "", "companions": "", "kind": "旅行",
                          "kb_link": ""})
    if new_trips:
        old_trips = read_rows(data_dir / "trips.csv")
        write_rows(data_dir / "trips.csv", TRIP_FIELDS, old_trips + new_trips)

    keep = [r for r in rows if r not in accept]
    write_rows(pending_path, PENDING_FIELDS, keep)
    return {"accepted": len(accept), "kept": len(keep), "new_trips": len(new_trips)}
