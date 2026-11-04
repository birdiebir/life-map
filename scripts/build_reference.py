r"""把下載的公開資料整理成 reference\。

來源（放在 --src 資料夾，結構見 README「重建參考資料」）：
- world-atlas（Natural Earth）countries-50m.json
- taiwan-atlas towns-10t.json（內政部界線；套件內中文名已損毀，只用代碼與形狀）
- 內政部國土測繪中心 API ListCounty／ListTown1 的 XML（中文名）
- GeoNames countryInfo.txt、cities15000.txt
- vendor：d3.min.js、topojson-client.min.js

國名中文用 Node 的 Intl.DisplayNames（zh-Hant-TW）產生，需要 node。
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference"
VENDOR = ROOT / "vendor"

ZH_OVERRIDES = {"HK": "香港", "MO": "澳門", "TW": "台灣", "PS": "巴勒斯坦", "KR": "南韓", "KP": "北韓"}


def zh_country_names(iso2_list: list[str]) -> dict[str, str]:
    js = (
        "const d=new Intl.DisplayNames(['zh-Hant-TW'],{type:'region'});"
        "const codes=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "const o={};for(const c of codes){try{o[c]=d.of(c)}catch(e){o[c]=''}}"
        "process.stdout.write(JSON.stringify(o));"
    )
    out = subprocess.run(["node", "-e", js], input=json.dumps(iso2_list), capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    names = json.loads(out)
    names.update({k: v for k, v in ZH_OVERRIDES.items() if k in names})
    return names


def build_countries(src: Path) -> tuple[dict[str, str], dict[str, str]]:
    """回傳（numeric -> C-ISO3, iso2 -> C-ISO3）對照，供地圖形狀與城市加 ID。"""
    rows = []
    for line in (src / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        rows.append({"iso2": f[0], "iso3": f[1], "numeric": f[2].zfill(3), "name_en": f[4],
                     "continent": f[8], "population": f[7], "capital": f[5]})
    zh = zh_country_names([r["iso2"] for r in rows])
    out = REF / "world" / "countries.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "iso2", "iso3", "numeric", "name_en", "name_zh", "continent", "population", "capital"])
        for r in rows:
            w.writerow([f"C-{r['iso3']}", r["iso2"], r["iso3"], r["numeric"], r["name_en"],
                        zh.get(r["iso2"], ""), r["continent"], r["population"], r["capital"]])
    print(f"countries.csv：{len(rows)} 筆")
    return {r["numeric"]: f"C-{r['iso3']}" for r in rows}, {r["iso2"]: f"C-{r['iso3']}" for r in rows}


def build_cities(src: Path, iso2_to_id: dict[str, str]) -> None:
    csv.field_size_limit(10**9)
    out = REF / "world" / "cities.csv"
    n = 0
    with (src / "cities15000.txt").open(encoding="utf-8") as fin, out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name_en", "country_id", "lat", "lon", "population", "is_capital"])
        for r in csv.reader(fin, delimiter="\t", quoting=csv.QUOTE_NONE):
            cid = iso2_to_id.get(r[8])
            if not cid:
                continue
            w.writerow([f"CITY-{r[0]}", r[1], cid, r[4], r[5], r[14], "1" if r[7] == "PPLC" else "0"])
            n += 1
    print(f"cities.csv：{n} 筆")


def build_world_topo(src: Path, numeric_to_id: dict[str, str]) -> None:
    topo = json.loads((src / "countries-50m.json").read_text(encoding="utf-8"))
    for g in topo["objects"]["countries"]["geometries"]:
        g["id"] = numeric_to_id.get(str(g.get("id", "")).zfill(3), "")
        g["properties"] = {"name": g.get("properties", {}).get("name", "")}
    del topo["objects"]["land"]
    (REF / "world" / "countries-50m.json").write_text(json.dumps(topo, separators=(",", ":")), encoding="utf-8")


def build_taiwan(src: Path) -> None:
    county_xml = ET.parse(src / "nlsc" / "county.xml").getroot()
    counties = {}
    letters = {}
    for it in county_xml.iter("countyItem"):
        code = it.findtext("countycode01")
        counties[code] = it.findtext("countyname")
        letters[it.findtext("countycode")] = code
    towns = {}
    for letter in letters:
        root = ET.parse(src / "nlsc" / f"town_{letter}.xml").getroot()
        for it in root.iter("townItem"):
            towns[it.findtext("towncode")] = it.findtext("townname")

    topo = json.loads((src / "towns-10t.json").read_text(encoding="utf-8"))
    town_geoms = topo["objects"]["towns"]["geometries"]
    county_geoms = topo["objects"]["counties"]["geometries"]
    missing = [g["properties"]["TOWNCODE"] for g in town_geoms if g["properties"]["TOWNCODE"] not in towns]
    if missing or len(town_geoms) != len(towns):
        sys.exit(f"鄉鎮代碼對不上：缺 {missing}，形狀 {len(town_geoms)}、名稱 {len(towns)}")

    with (REF / "taiwan" / "counties.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name_en", "name_zh"])
        for g in county_geoms:
            p = g["properties"]
            w.writerow([f"TW-{p['COUNTYCODE']}", p["COUNTYENG"], counties[p["COUNTYCODE"]]])
    with (REF / "taiwan" / "towns.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name_en", "name_zh", "county_id"])
        for g in town_geoms:
            p = g["properties"]
            w.writerow([f"TW-{p['TOWNCODE']}", p["TOWNENG"], towns[p["TOWNCODE"]], f"TW-{p['COUNTYCODE']}"])

    for g in town_geoms:
        g["id"] = f"TW-{g['properties']['TOWNCODE']}"
        g["properties"] = {}
    for g in county_geoms:
        g["id"] = f"TW-{g['properties']['COUNTYCODE']}"
        g["properties"] = {}
    for g in topo["objects"]["nation"]["geometries"]:
        g["id"] = "C-TWN"
        g["properties"] = {}
    (REF / "taiwan" / "taiwan-10t.json").write_text(json.dumps(topo, separators=(",", ":")), encoding="utf-8")
    print(f"台灣：{len(county_geoms)} 縣市、{len(town_geoms)} 鄉鎮")


def copy_vendor(src: Path) -> None:
    VENDOR.mkdir(exist_ok=True)
    for name in ("d3.min.js", "topojson-client.min.js"):
        shutil.copy(src / name, VENDOR / name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path, help="整理好的下載資料夾")
    a = ap.parse_args()
    (REF / "world").mkdir(parents=True, exist_ok=True)
    (REF / "taiwan").mkdir(parents=True, exist_ok=True)
    numeric_to_id, iso2_to_id = build_countries(a.src)
    build_cities(a.src, iso2_to_id)
    build_world_topo(a.src, numeric_to_id)
    build_taiwan(a.src)
    copy_vendor(a.src)


if __name__ == "__main__":
    main()
