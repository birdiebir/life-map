r"""照片地點匯入：Google 相簿 JSON、照片目錄 CSV、候選格式、只新增、已涵蓋不重複。全部用假資料。"""
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from _ach import ROOT
from lifemap.pending import PENDING_FIELDS, add_candidates, read_rows, write_rows
from lifemap.photoloc import parse_gps, read_catalog_csv, read_google_photos_dir, read_sources

TAIPEI101 = (25.0340, 121.5645)       # 信義區
TOKYO = (35.68, 139.76)
HEADER = "visit_id,place_id,date_start,date_end,level,together,trip_id,memory,photo,source,confidence,confirmed\n"


def ts(y, m, d, h=4):
    return str(int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp()))


def sidecar(lat, lon, y, m, d, exif=True):
    g = {"latitude": lat, "longitude": lon, "altitude": 0.0}
    return {"photoTakenTime": {"timestamp": ts(y, m, d)}, "creationTime": {"timestamp": ts(2026, 1, 1)},
            "geoDataExif" if exif else "geoData": g}


def write_dir(root):
    (root / "相簿").mkdir(parents=True)
    files = {
        "a.jpg.json": sidecar(*TAIPEI101, 2024, 3, 10),
        "b.jpg.supplemental-metadata.json": sidecar(*TAIPEI101, 2024, 3, 10, exif=False),    # 同地同天 → 合併
        "c.jpg.json": sidecar(*TOKYO, 2024, 5, 1),
        "d.jpg.json": sidecar(0.0, 0.0, 2024, 5, 2),                                           # 0,0＝沒有
        "e.jpg.json": {"photoTakenTime": {"timestamp": ts(2024, 5, 3)}},                       # 沒座標
        "相簿/metadata.json": {"title": "某相簿"},                                              # 不是照片
    }
    for n, d in files.items():
        (root / n).write_text(json.dumps(d), encoding="utf-8")
    (root / "壞掉.json").write_text("{", encoding="utf-8")


def write_csv_file(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_id", "date_taken", "date_precision", "gps"])
        w.writerows(rows)


def test_parse_gps():
    assert parse_gps("25.03,121.56") == (25.03, 121.56)
    assert parse_gps("25.03 121.56") == (25.03, 121.56)
    assert parse_gps("-37.8; 145.0") == (-37.8, 145.0)
    for bad in ("", "0,0", "0.0,0.0", "95,10", "25.03", "abc", "25,03,121,56", "25,03 121,56", "x 25.03,121.56 y"):
        assert parse_gps(bad) is None


def test_read_google_photos_dir(tmp_path):
    write_dir(tmp_path)
    obs, st = read_google_photos_dir({"path": str(tmp_path)})
    assert st == {"rows": 5, "no_gps": 2, "date_not_day": 0}
    assert len(obs) == 3 and all(o.source == "photo" and o.ref == "" for o in obs)
    assert sorted(o.day.isoformat() for o in obs) == ["2024-03-10", "2024-03-10", "2024-05-01"]


def test_read_catalog_csv(tmp_path):
    p = tmp_path / "c.csv"
    write_csv_file(p, [["1", "2024-03-10", "day", "25.034,121.5645"], ["2", "2024-03-10", "day", ""],
                       ["3", "2024-03", "month", "25.034,121.5645"], ["4", "壞", "day", "25.034,121.5645"],
                       ["5", "2024-05-01", "day", "0,0"]])
    obs, st = read_catalog_csv({"path": str(p)})
    assert st == {"rows": 5, "no_gps": 2, "date_not_day": 2}
    assert [o.day.isoformat() for o in obs] == ["2024-03-10"] and obs[0].lat == 25.034


def test_custom_columns(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("d,p,loc\n2024-03-10,day,\"25.034,121.5645\"\n", encoding="utf-8")
    obs, _ = read_catalog_csv({"path": str(p), "gps_col": "loc", "date_col": "d", "precision_col": "p"})
    assert len(obs) == 1


def test_read_sources_disabled_missing_unknown(tmp_path):
    write_dir(tmp_path)
    obs, rep = read_sources([{"type": "google_photos_dir", "path": str(tmp_path), "label": "G"},
                             {"type": "google_photos_dir", "path": str(tmp_path / "不存在"), "enabled": False}])
    assert len(obs) == 3 and rep[0][0] == "G" and rep[0][1]["usable"] == 3 and len(rep) == 1
    with pytest.raises(FileNotFoundError):
        read_sources([{"type": "catalog_csv", "path": str(tmp_path / "沒有.csv")}])
    with pytest.raises(ValueError):
        read_sources([{"type": "xx", "path": str(tmp_path)}])


def mk_data(base, sources, visits=()):
    base.mkdir(parents=True)
    (base / "visits.csv").write_text(HEADER + "".join(v + "\n" for v in visits), encoding="utf-8")
    (base / "sources.json").write_text(json.dumps({"photo_sources": sources}, ensure_ascii=False), encoding="utf-8")
    return base


def run(d, *args):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "import_photo_locations.py"),
                           "--data-dir", str(d), *args], capture_output=True, text=True, encoding="utf-8")


def test_script_dry_run_then_write_merges_same_place_same_day(tmp_path):
    ph = tmp_path / "ph"
    write_dir(ph)
    d = mk_data(tmp_path / "data", [{"type": "google_photos_dir", "path": str(ph), "label": "Google 相簿"}])
    r = run(d)
    assert r.returncode == 0 and "試跑" in r.stdout and "可用 3 筆" in r.stdout, r.stdout + r.stderr
    assert not (d / "pending.csv").exists()
    r = run(d, "--write")
    assert r.returncode == 0 and "新增 3 筆" in r.stdout, r.stdout + r.stderr          # 信義區＋台北 101 景點＋東京
    rows = read_rows(d / "pending.csv")
    assert {x["place_id"] for x in rows} == {"TW-63000020", "TWP-CH-016", "CITY-1850147"}
    xin = next(x for x in rows if x["place_id"] == "TW-63000020")
    assert xin["date_start"] == "2024-03-10" and xin["level"] == "3" and xin["source"] == "photo"      # 同一天 2 張合成 1 筆
    assert xin["confirmed"] == "false" and xin["decision"] == ""
    assert "照片來源：Google 相簿" in xin["evidence"] and "照片 2" in xin["evidence"]
    assert "25.03" not in (d / "pending.csv").read_text(encoding="utf-8")                              # 座標不外流
    r = run(d, "--write")                                                                              # 重跑：不重複
    assert "新增 0 筆" in r.stdout and len(read_rows(d / "pending.csv")) == 3


def test_already_in_visits_not_duplicated(tmp_path):
    ph = tmp_path / "ph"
    write_dir(ph)
    d = mk_data(tmp_path / "data", [{"type": "google_photos_dir", "path": str(ph)}],
                visits=["v1,TW-63000020,2024-03-10,,3,false,,,,manual,,true"])
    r = run(d, "--write")
    assert "已有足跡涵蓋而略過 1 筆" in r.stdout, r.stdout + r.stderr
    assert {x["place_id"] for x in read_rows(d / "pending.csv")} == {"CITY-1850147", "TWP-CH-016"}   # 景點是另一個地點，照舊產生


def test_csv_source_keeps_other_pending_rows(tmp_path):
    p = tmp_path / "c.csv"
    write_csv_file(p, [["1", "2024-05-01", "day", "35.68,139.76"]])
    d = mk_data(tmp_path / "data", [{"type": "catalog_csv", "path": str(p), "label": "photo-catalog"}])
    base = {f: "" for f in PENDING_FIELDS}
    write_rows(d / "pending.csv", PENDING_FIELDS, [
        {**base, "visit_id": "TK-1", "place_id": "C-AUS", "date_start": "2020-01-01"},
        {**base, "visit_id": "TK-2", "place_id": "C-JPN", "date_start": "2019-01-01", "decision": "n"}])
    r = run(d, "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    rows = read_rows(d / "pending.csv")
    assert len(rows) == 3 and {"TK-1", "TK-2"} <= {x["visit_id"] for x in rows}     # 舊的未決定列沒被丟掉
    assert "photo-catalog" in next(x for x in rows if x["place_id"] == "CITY-1850147")["evidence"]


def test_no_gps_gives_zero_candidates(tmp_path):
    p = tmp_path / "c.csv"
    write_csv_file(p, [["1", "2024-05-01", "day", ""], ["2", "2024-05-02", "day", ""]])
    d = mk_data(tmp_path / "data", [{"type": "catalog_csv", "path": str(p)}])
    r = run(d, "--write")
    assert r.returncode == 0 and "候選 0 筆" in r.stdout and "新增 0 筆" in r.stdout
    assert not (d / "pending.csv").exists()


def test_errors(tmp_path):
    d = mk_data(tmp_path / "a", [])
    assert run(d).returncode == 1
    d2 = mk_data(tmp_path / "b", [{"type": "catalog_csv", "path": str(tmp_path / "不存在.csv")}])
    assert run(d2).returncode == 1
    assert run(d, "--write", "--example").returncode != 0


def test_add_candidates_only_adds(tmp_path):
    p = tmp_path / "pending.csv"
    base = {f: "" for f in PENDING_FIELDS}
    write_rows(p, PENDING_FIELDS, [{**base, "visit_id": "A", "decision": "y", "level": "4", "date_start": "2020"}])
    n = add_candidates(p, [{**base, "visit_id": "A", "level": "2"}, {**base, "visit_id": "B", "date_start": "2019"}])
    assert n == (1, 1)
    rows = {r["visit_id"]: r for r in read_rows(p)}
    assert rows["A"]["decision"] == "y" and rows["A"]["level"] == "4" and "B" in rows


def test_last_scan_non_dict_state_is_ignored(tmp_path):
    from lifemap.ach_scan import STATE, last_scan
    (tmp_path / STATE).write_text("[1, 2]", encoding="utf-8")
    assert last_scan(tmp_path) is None
