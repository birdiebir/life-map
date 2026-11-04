"""離線判斷座標落在哪個國家／城市／台灣縣市鄉鎮（不呼叫任何外部 API）。"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

from shapely import STRtree
from shapely.geometry import MultiPolygon, Point, Polygon

from .reference import Place

KM_PER_DEG = 111.32


def decode_topo(topo: dict, obj_name: str) -> list[tuple[str, Polygon | MultiPolygon]]:
    """TopoJSON 物件 → [(id, shapely 幾何)]，跳過沒有 ID 的形狀。"""
    tf = topo.get("transform")
    arcs = []
    for arc in topo["arcs"]:
        pts, x, y = [], 0, 0
        for p in arc:
            if tf:
                x, y = x + p[0], y + p[1]
                pts.append((x * tf["scale"][0] + tf["translate"][0], y * tf["scale"][1] + tf["translate"][1]))
            else:
                pts.append((p[0], p[1]))
        arcs.append(pts)

    def ring(idx: list[int]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for k, i in enumerate(idx):
            c = arcs[i] if i >= 0 else arcs[~i][::-1]
            out.extend(c if k == 0 else c[1:])
        return out

    def poly(rings: list[list[int]]) -> Polygon | None:
        rs = [ring(r) for r in rings]
        rs = [r for r in rs if len(r) >= 4]
        return Polygon(rs[0], rs[1:]) if rs else None

    out = []
    for g in topo["objects"][obj_name]["geometries"]:
        gid = g.get("id")
        if not gid:
            continue
        if g["type"] == "Polygon":
            geom = poly(g["arcs"])
        elif g["type"] == "MultiPolygon":
            parts = [p for p in (poly(a) for a in g["arcs"]) if p is not None]
            geom = MultiPolygon(parts) if parts else None
        else:
            geom = None
        if geom is not None:
            out.append((gid, geom.buffer(0)))
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Location:
    country: str
    city: str | None = None
    tw_county: str | None = None
    tw_town: str | None = None
    poi: str | None = None  # 景點／世界遺產（同一個點另外產生一筆）

    @property
    def place_id(self) -> str:
        """最細的一層：景點；台灣到鄉鎮，其他國家到城市，找不到城市就到國家。"""
        return self.poi or self.tw_town or self.city or self.country

    @property
    def region(self) -> str:
        """分旅程用的範圍：台灣看縣市，其他看國家。"""
        return self.tw_county or self.country


class _Index:
    def __init__(self, items: list[tuple[str, Polygon | MultiPolygon]]):
        self.ids = [i for i, _ in items]
        self.geoms = [g for _, g in items]
        self.tree = STRtree(self.geoms)

    def find(self, pt: Point, snap_km: float) -> str | None:
        hits = self.tree.query(pt, predicate="intersects")
        if len(hits):
            return self.ids[int(hits[0])]
        idx = self.tree.nearest(pt)
        if idx is None:
            return None
        lat_scale = max(math.cos(math.radians(pt.y)), 0.2)
        if self.geoms[int(idx)].distance(pt) * KM_PER_DEG * lat_scale <= snap_km:
            return self.ids[int(idx)]
        return None


class Locator:
    def __init__(self, ref_dir: Path, places: dict[str, Place], cfg: dict):
        self.places, self.cfg = places, cfg
        world = json.loads((ref_dir / "world" / "countries-50m.json").read_text(encoding="utf-8"))
        tw = json.loads((ref_dir / "taiwan" / "taiwan-10t.json").read_text(encoding="utf-8"))
        self.world = _Index(decode_topo(world, "countries"))
        self.towns = _Index(decode_topo(tw, "towns"))
        with (ref_dir / "world" / "countries.csv").open(encoding="utf-8") as fh:
            self.iso2 = {r["iso2"]: r["id"] for r in csv.DictReader(fh)}
        self.cities: dict[str, list[tuple[str, float, float, int]]] = {}
        with (ref_dir / "world" / "cities.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                self.cities.setdefault(r["country_id"], []).append(
                    (r["id"], float(r["lat"]), float(r["lon"]), int(r["population"] or 0)))
        whs_r = cfg.get("whs_radius_km", 3)
        # 大範圍景點（國家風景區等）只用一個代表點近似，半徑上限 area_max 避免把整個都會區都算進去
        area_max = cfg.get("poi_max_radius_km", 8)
        self.pois = [(p.id, p.lat, p.lon, min(p.radius_km, area_max) if p.kind == "tw_poi" else whs_r)
                     for p in places.values() if p.kind in ("tw_poi", "whs") and p.lat is not None]

    def pois_near(self, lat: float, lon: float) -> list[str]:
        """座標落在哪些景點／世界遺產的判定半徑內。"""
        out = []
        for pid, plat, plon, r in self.pois:
            if abs(plat - lat) * 111 > r + 1:  # 先用緯度差粗篩
                continue
            if haversine_km(lat, lon, plat, plon) <= r:
                out.append(pid)
        return out

    def _city(self, country: str, lat: float, lon: float) -> str | None:
        """半徑內的大城市用「人口 ÷ (1 + 距離/10)²」挑，避免東京市中心被判成中央區這種行政區；
        附近沒有大城市才退回最近的小城市（例如法國米約）。"""
        best_big, best_any = None, None
        for cid, clat, clon, pop in self.cities.get(country, []):
            d = haversine_km(lat, lon, clat, clon)
            if pop >= self.cfg["city_min_population"] and d <= self.cfg["city_radius_km"]:
                score = pop / (1 + d / 10) ** 2
                if best_big is None or score > best_big[0]:
                    best_big = (score, cid)
            if d <= self.cfg["city_small_radius_km"] and (best_any is None or d < best_any[0]):
                best_any = (d, cid)
        return (best_big or best_any or (None, None))[1]

    def locate(self, lat: float | None, lon: float | None, country_hint: str | None = None) -> Location | None:
        """country_hint 是 ISO2（評論附的國碼），座標缺漏或落在海上找不到國家時才用。"""
        hint = self.iso2.get(country_hint or "")
        if lat is None or lon is None:
            return Location(hint) if hint else None
        pt = Point(lon, lat)
        town = self.towns.find(pt, self.cfg["taiwan_snap_km"])
        if town:
            return Location("C-TWN", tw_county=self.places[town].parent, tw_town=town)
        country = self.world.find(pt, self.cfg["country_snap_km"]) or hint
        if not country:
            return None
        return Location(country, city=self._city(country, lat, lon))
