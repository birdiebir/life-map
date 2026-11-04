r"""M3 參考資料：台灣縣市鄉鎮代表點、世界遺產、精選城市、旅遊警示、聯合國會員、台灣景點。

python scripts\build_reference_m3.py [--src <資料夾>]

- 不帶 --src：只幫 reference\taiwan\counties.csv、towns.csv 補代表點（lat、lon）。
- --src 指向整理好的資料夾，裡面有（有哪個就處理哪個）：
  world\out\whs.csv、city_lists.csv、travel_warnings.csv、un_members.csv
  taiwan\out\poi.csv
精選城市規則見規格書 §6.2，結果寫到 reference\world\curated_cities.csv（status=include／exclude＋理由），
使用者審過一次才定案（改 status 就好）。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import paths  # noqa: E402
from lifemap.geo import decode_topo, haversine_km  # noqa: E402

REF = paths.REFERENCE


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def add_taiwan_centroids() -> None:
    topo = json.loads((REF / "taiwan" / "taiwan-10t.json").read_text(encoding="utf-8"))
    for obj, name in (("towns", "towns.csv"), ("counties", "counties.csv")):
        pts = {gid: g.representative_point() for gid, g in decode_topo(topo, obj)}
        rows = read(REF / "taiwan" / name)
        for r in rows:
            p = pts[r["id"]]
            r["lat"], r["lon"] = f"{p.y:.5f}", f"{p.x:.5f}"
        fields = [f for f in rows[0] if f not in ("lat", "lon")] + ["lat", "lon"]
        write(REF / "taiwan" / name, fields, rows)
    print("台灣縣市、鄉鎮代表點：完成")


def curate_cities(world_out: Path) -> None:
    cities = read(REF / "world" / "cities.csv")
    by_id = {c["id"]: c for c in cities}
    lists: dict[str, dict[str, int]] = defaultdict(dict)  # city_id → {list: rank}
    if (world_out / "city_lists.csv").exists():
        for r in read(world_out / "city_lists.csv"):
            if r["city_id"] in by_id:
                lists[r["city_id"]][r["list"]] = int(r["rank"]) if r["rank"].isdigit() else 999
    whs = read(REF / "world" / "whs.csv") if (REF / "world" / "whs.csv").exists() else []
    whs_by_country: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for w in whs:
        if w["lat"] and w["lon"]:
            for c in w["country_ids"].split(";"):
                whs_by_country[c].append((float(w["lat"]), float(w["lon"])))
    warn_country, warn_region = {}, defaultdict(list)
    if (world_out / "travel_warnings.csv").exists():
        for r in read(world_out / "travel_warnings.csv"):
            if r["region"]:
                warn_region[r["country_id"]].append((r["region"], r["level"]))
            else:
                warn_country[r["country_id"]] = r["level"]

    # 2026-10-12 調整（Euromonitor 完整 100 名付費、EIU 只公開前段）：
    # 熱門＝任一份 Euromonitor 名單有列（2025 公開名次／2025 旅客前 10／2018 旅客前 100）；宜居＝EIU 前 50；
    # 世界遺產看 WHS_KM 公里內。
    WHS_KM, EIU_TOP = 20, 50
    LABEL = {"euromonitor_top100": "Euromonitor 2025", "euromonitor_arrivals_top10": "旅客量 2025",
             "euromonitor_arrivals_2018": "旅客量 2018"}

    def em_rank(cid: str) -> int | None:
        rs = [lists[cid][k] for k in ("euromonitor_arrivals_top10", "euromonitor_top100", "euromonitor_arrivals_2018")
              if k in lists[cid]]
        return rs[0] if rs else None

    pool = [c for c in cities if c["is_capital"] == "1" or int(c["population"] or 0) >= 1_000_000 or c["id"] in lists]
    out = []
    for c in pool:
        cid, country = c["id"], c["country_id"]
        lat, lon = float(c["lat"]), float(c["lon"])
        n_whs = sum(1 for wl, wo in whs_by_country.get(country, []) if haversine_km(lat, lon, wl, wo) <= WHS_KM)
        reasons = []
        if c["is_capital"] == "1":
            reasons.append("首都")
        if int(c["population"] or 0) >= 1_000_000:
            reasons.append(f"人口 {int(c['population']) // 10000} 萬")
        for name, label in LABEL.items():
            if name in lists[cid]:
                reasons.append(f"{label} #{lists[cid][name]}")
        eiu = lists[cid].get("eiu_liveability")
        if eiu:
            reasons.append(f"EIU 宜居 #{eiu}")
        if n_whs:
            reasons.append(f"{WHS_KM} km 內世界遺產 {n_whs} 處")
        quality = em_rank(cid) is not None or (eiu is not None and eiu <= EIU_TOP) or n_whs > 0
        level = warn_country.get(country, "")
        region_hits = [lv for reg, lv in warn_region.get(country, []) if c["name_en"].lower() in reg.lower()]
        if level in ("red", "orange") or any(lv in ("red", "orange") for lv in region_hits):
            status = "exclude"
            reasons.append(f"排除：外交部旅遊警示 {level or region_hits[0]}")
        elif not quality:
            continue
        else:
            status = "include"
            if level == "yellow":
                reasons.append("注意：外交部全國黃色警示")
            regional = [lv for _, lv in warn_region.get(country, []) if lv in ("red", "orange")]
            if regional:
                reasons.append(f"注意：國內有地區{'紅' if 'red' in regional else '橙'}色警示，請確認這個城市是否在範圍內")
        out.append({"city_id": cid, "name_en": c["name_en"], "name_zh": "", "country_id": country,
                    "status": status, "euromonitor_rank": em_rank(cid) or "",
                    "eiu_rank": eiu or "", "whs_nearby": n_whs, "reasons": "；".join(reasons)})
    out.sort(key=lambda r: (r["status"] != "include", r["euromonitor_rank"] or 999, r["name_en"]))
    old = {r["city_id"]: r for r in read(REF / "world" / "curated_cities.csv")} \
        if (REF / "world" / "curated_cities.csv").exists() else {}
    for r in out:  # 使用者審過的 status、中文名保留
        if r["city_id"] in old:
            r["status"] = old[r["city_id"]]["status"]
            r["name_zh"] = old[r["city_id"]].get("name_zh", "")
    write(REF / "world" / "curated_cities.csv",
          ["city_id", "name_en", "name_zh", "country_id", "status", "euromonitor_rank", "eiu_rank", "whs_nearby",
           "reasons"], out)
    print(f"精選城市：收 {sum(r['status'] == 'include' for r in out)}、排除 {sum(r['status'] == 'exclude' for r in out)}")


def locate_pois(tw_out: Path) -> None:
    from lifemap.geo import Locator
    from lifemap.reference import load_places
    places = load_places(REF)
    loc = Locator(REF, places, paths.config("import"))
    rows = read(tw_out / "poi.csv")
    missing = 0
    for r in rows:
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except ValueError:
            r["town_id"] = ""
            missing += 1
            continue
        hit = loc.locate(lat, lon)
        r["town_id"] = hit.tw_town if hit and hit.tw_town else ""
        if hit and hit.tw_county and not r.get("county_id"):
            r["county_id"] = hit.tw_county
        missing += not r["town_id"]
    fields = ["id", "tier", "set", "name_zh", "name_en", "lat", "lon", "radius_km", "county_id", "town_id",
              "source", "source_id", "note"]
    write(REF / "taiwan" / "poi.csv", fields, rows)
    print(f"台灣景點：{len(rows)} 個，判不到鄉鎮 {missing} 個（掛在縣市底下）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path)
    a = ap.parse_args()
    add_taiwan_centroids()
    if not a.src:
        return
    world_out, tw_out = a.src / "world" / "out", a.src / "taiwan" / "out"
    for name in ("whs.csv", "un_members.csv", "travel_warnings.csv", "city_lists.csv"):
        if (world_out / name).exists():
            rows = read(world_out / name)
            write(REF / "world" / name, list(rows[0]), rows)
            print(f"{name}：{len(rows)} 列")
    curate_cities(world_out)
    if (tw_out / "poi.csv").exists():
        locate_pois(tw_out)


if __name__ == "__main__":
    main()
