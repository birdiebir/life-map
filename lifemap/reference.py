r"""讀取 reference\ 的公開地名資料。

必要：world\countries.csv、world\cities.csv、taiwan\counties.csv、taiwan\towns.csv。
選用（M3，有檔案才載入）：
- world\city_names_zh.csv → 城市中文名（只收範例會用到的幾個）；world\city_names_zh.local.csv 是自己加的覆寫（不進 git）
- world\un_members.csv → 國家加標籤 un194（聯合國 193 國＋台灣）
- world\curated_cities.csv → status=include 的城市加標籤 curated
- world\whs.csv → 世界遺產（kind=whs，掛在第一個所屬國家底下）
- taiwan\poi.csv → 台灣景點（kind=tw_poi，掛在所在鄉鎮底下，標籤 tier1／tier2／tier3 與 set 名稱）
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Place:
    id: str
    kind: str  # country / city / tw_county / tw_town / whs / tw_poi
    name_en: str
    name_zh: str
    parent: str | None = None
    continent: str | None = None
    lat: float | None = None
    lon: float | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    radius_km: float | None = None  # 景點判定「去過」的半徑

    @property
    def name(self) -> str:
        return self.name_zh or self.name_en


def _rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        yield from csv.DictReader(fh)


def _float(s: str | None) -> float | None:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def load_places(ref_dir: Path) -> dict[str, Place]:
    places: dict[str, Place] = {}
    world, tw = ref_dir / "world", ref_dir / "taiwan"

    un = {r["country_id"] for r in _rows(world / "un_members.csv")} if (world / "un_members.csv").exists() else set()
    if un:
        un.add("C-TWN")
    for r in _rows(world / "countries.csv"):
        places[r["id"]] = Place(r["id"], "country", r["name_en"], r["name_zh"], continent=r["continent"],
                                tags=frozenset({"un194"} if r["id"] in un else ()))

    zh_city: dict[str, str] = {}
    for fn in ("city_names_zh.csv", "city_names_zh.local.csv"):  # .local 是自己加的覆寫，不進 git
        if (world / fn).exists():
            zh_city.update({r["id"]: r["name_zh"] for r in _rows(world / fn)})
    curated = {r["city_id"]: r.get("name_zh", "") for r in _rows(world / "curated_cities.csv")
               if r.get("status") == "include"} if (world / "curated_cities.csv").exists() else {}
    for r in _rows(world / "cities.csv"):
        cid = r["id"]
        places[cid] = Place(cid, "city", r["name_en"], zh_city.get(cid) or curated.get(cid, ""),
                            parent=r["country_id"], lat=float(r["lat"]), lon=float(r["lon"]),
                            tags=frozenset({"curated"} if cid in curated else ()))

    if (world / "whs.csv").exists():
        for r in _rows(world / "whs.csv"):
            countries = [c for c in r["country_ids"].split(";") if c in places]
            lat, lon = _float(r["lat"]), _float(r["lon"])
            if not countries or lat is None or lon is None:
                continue
            places[r["id"]] = Place(r["id"], "whs", r["name_en"], r.get("name_zh", ""), parent=countries[0],
                                    lat=lat, lon=lon, tags=frozenset({r.get("category", "")} - {""}))

    for r in _rows(tw / "counties.csv"):
        places[r["id"]] = Place(r["id"], "tw_county", r["name_en"], r["name_zh"], parent="C-TWN",
                                lat=_float(r.get("lat")), lon=_float(r.get("lon")))
    for r in _rows(tw / "towns.csv"):
        places[r["id"]] = Place(r["id"], "tw_town", r["name_en"], r["name_zh"], parent=r["county_id"],
                                lat=_float(r.get("lat")), lon=_float(r.get("lon")))

    if (tw / "poi.csv").exists():
        for r in _rows(tw / "poi.csv"):
            parent = r.get("town_id") or r.get("county_id")
            if parent not in places:
                continue
            places[r["id"]] = Place(r["id"], "tw_poi", r.get("name_en", ""), r["name_zh"], parent=parent,
                                    lat=_float(r["lat"]), lon=_float(r["lon"]),
                                    tags=frozenset({f"tier{r['tier']}", r["set"]}),
                                    radius_km=_float(r.get("radius_km")) or 0.3)
    return places
