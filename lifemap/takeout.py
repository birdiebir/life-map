"""從 Google Takeout zip 唯讀讀出「到過哪裡」的觀察點：地圖評論、上傳到地圖的照片。

不解壓縮、不讀「已加上標籤的地點」（住家／公司）。
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REVIEWS = "評論.json"
PHOTO_DIR = "/相片和影片/"


@dataclass(frozen=True)
class Observation:
    source: str  # review / photo
    day: date  # 當地日期（用經度粗估時區）
    lat: float | None
    lon: float | None
    label: str
    ref: str  # 照片：zip:<zip 路徑>!<檔名>；評論：Google 地圖網址
    country_hint: str | None = None  # ISO2，座標缺漏時備用


def local_day(utc: datetime, lon: float | None) -> date:
    offset = round(lon / 15) if lon is not None else 8
    return (utc + timedelta(hours=offset)).date()


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _valid(lat, lon) -> bool:
    return lat is not None and lon is not None and not (abs(lat) < 1e-9 and abs(lon) < 1e-9)


def read_reviews(z: zipfile.ZipFile) -> list[Observation]:
    out = []
    for name in z.namelist():
        if not name.endswith("/" + REVIEWS):
            continue
        for f in json.loads(z.read(name).decode("utf-8")).get("features", []):
            props = f.get("properties", {})
            loc = props.get("location", {})
            lon, lat = (f.get("geometry", {}).get("coordinates") or [None, None])[:2]
            if not _valid(lat, lon):
                lat = lon = None
            if lat is None and not loc.get("country_code"):
                continue
            when = _iso(props["date"])
            out.append(Observation("review", local_day(when, lon), lat, lon, loc.get("name", ""),
                                   props.get("google_maps_url", ""), loc.get("country_code")))
    return out


def photo_observation(d: dict, ref: str = "") -> Observation | None:
    """照片旁的 JSON（photoTakenTime／creationTime／geoData）→ 觀察點；沒座標（含 0,0）或沒時間回傳 None。"""
    g = d.get("geoDataExif") or d.get("geoData") or {}
    lat, lon = g.get("latitude"), g.get("longitude")
    if not _valid(lat, lon):
        return None
    taken = (d.get("photoTakenTime") or {}).get("timestamp")
    created = (d.get("creationTime") or {}).get("timestamp")
    ts = taken or created
    if not ts:
        return None
    when = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    # 拍攝時間晚於上傳時間＝EXIF 的當地時間被當成 UTC 存，不能再加時差（查核發現）
    day = when.date() if taken and created and int(taken) > int(created) else local_day(when, lon)
    return Observation("photo", day, lat, lon, "", ref)


def read_photos(z: zipfile.ZipFile, zip_path: Path) -> list[Observation]:
    out = []
    names = set(z.namelist())
    for name in names:
        if PHOTO_DIR not in name or not name.endswith(".json"):
            continue
        d = json.loads(z.read(name).decode("utf-8"))
        media = name[: -len(".json")]
        o = photo_observation(d, f"zip:{zip_path}!{media}" if media in names else "")
        if o:
            out.append(o)
    return out


def read_takeout(zip_path: Path) -> list[Observation]:
    with zipfile.ZipFile(zip_path) as z:
        return read_reviews(z) + read_photos(z, zip_path)
