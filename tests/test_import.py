import csv
import json
import zipfile
from datetime import date

import pytest

import paths
from lifemap.data import DataError, Visit, load_visits
from lifemap.geo import Location, Locator
from lifemap.infer import build_candidates, covered
from lifemap.pending import PENDING_FIELDS, apply_pending, merge_pending, read_rows, write_rows
from lifemap.reference import Place, load_places
from lifemap.takeout import Observation, read_takeout


# ---------- 地點比對（用真的參考資料） ----------

@pytest.fixture(scope="module")
def real():
    places = load_places(paths.REFERENCE)
    return places, Locator(paths.REFERENCE, places, paths.config("import"))


@pytest.mark.parametrize("lat,lon,expect", [
    (25.0340, 121.5645, "TW-63000020"),   # 台北 101 → 信義區
    (24.43, 118.32, "TW-09020010"),       # 金門金城鎮
    (35.68, 139.76, "CITY-1850147"),      # 東京市中心不能被判成中央區
    (43.6950, 7.2650, "CITY-2990440"),    # 尼斯海濱（海邊）
    (44.098, 3.078, "CITY-2993875"),      # 米約（附近沒大城市，退回小城市）
])
def test_locate_known_points(real, lat, lon, expect):
    _, loc = real
    assert loc.locate(lat, lon).place_id == expect


def test_locate_sea_and_hint(real):
    _, loc = real
    assert loc.locate(43.05, 3.30).country == "C-FRA"  # 海上但靠岸，吸附到國家
    assert loc.locate(20, -150) is None                   # 太平洋中間
    assert loc.locate(None, None, "TH") == Location("C-THA")


# ---------- 讀 Takeout ----------

def _make_zip(path, reviews, photos):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Takeout/地圖 (你的地點)/評論.json", json.dumps({"type": "FeatureCollection", "features": reviews}))
        z.writestr("Takeout/地圖 (你的地點)/已加上標籤的地點.json", json.dumps({"features": [{"home": 1}]}))
        for name, meta in photos.items():
            z.writestr(f"Takeout/地圖/相片和影片/{name}.json", json.dumps(meta))
            z.writestr(f"Takeout/地圖/相片和影片/{name}", b"jpg-bytes")


def _review(lon, lat, when, name="店", cc=None):
    loc = {"name": name}
    if cc:
        loc["country_code"] = cc
    return {"geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"date": when, "location": loc, "google_maps_url": "u"}}


def test_read_takeout(tmp_path):
    zp = tmp_path / "t.zip"
    _make_zip(zp, [
        _review(139.7, 35.7, "2021-06-09T20:00:00Z", "A"),       # UTC 20:00 + 9h → 當地 10-10
        _review(0, 0, "2015-02-01T00:00:00Z", "B", cc="TH"),     # 座標缺漏，留國碼
        _review(0, 0, "2015-02-01T00:00:00Z", "C"),              # 座標和國碼都沒有 → 略過
    ], {
        "p1.jpg": {"photoTakenTime": {"timestamp": "1623268800"}, "geoDataExif": {"latitude": 35.66, "longitude": 139.70}},
        "p2.jpg": {"photoTakenTime": {"timestamp": "1623268800"}, "geoDataExif": {"latitude": 0.0, "longitude": 0.0}},
    })
    obs = read_takeout(zp)
    reviews = [o for o in obs if o.source == "review"]
    photos = [o for o in obs if o.source == "photo"]
    assert [(o.label, o.day) for o in reviews] == [("A", date(2021, 6, 10)), ("B", date(2015, 2, 1))]
    assert reviews[1].lat is None and reviews[1].country_hint == "TH"
    assert len(photos) == 1 and photos[0].ref == f"zip:{zp}!Takeout/地圖/相片和影片/p1.jpg"


# ---------- 推定候選 ----------

class StubLocator:
    def __init__(self, table):
        self.table = table

    def locate(self, lat, lon, hint=None):
        return self.table.get(lat)


TOKYO = Location("C-JPN", city="CITY-T")
DAAN = Location("C-TWN", tw_county="TW-63000", tw_town="TW-63000030")


@pytest.fixture
def stub_places(places):
    return {**places, "CITY-T": Place("CITY-T", "city", "Tokyo", "東京", parent="C-JPN")}


def O(day, lat, src="review", label="x"):
    return Observation(src, day, lat, 0.0, label, f"zip:z!{label}.jpg" if src == "photo" else "u")


def test_levels_and_trips(stub_places):
    loc = StubLocator({1: TOKYO, 2: DAAN})
    obs = [O(date(2024, 3, 10), 1, label="淺草"), O(date(2024, 3, 12), 1, "photo", "p"),  # 東京 2 天 → 4
           O(date(2024, 9, 1), 1, label="築地"),                                             # 半年後另一趟 → 2
           O(date(2023, 5, 1), 2, label="甲"), O(date(2023, 5, 1), 2, label="乙"),
           O(date(2023, 5, 1), 2, "photo", "大安照")]                                       # 大安同一天 3 筆（含照片）→ 3
    rows, stats = build_candidates(obs, loc, stub_places, [], gap_days=3)
    got = {(r["place_id"], r["date_start"]): r for r in rows}
    t1 = got[("CITY-T", "2024-03-10")]
    assert t1["level"] == 4 and t1["date_end"] == "2024-03-12" and t1["trip_id"] == "A-JPN-202403"
    assert t1["photo"] == "zip:z!p.jpg" and t1["evidence"] == "評論 1、照片 1"
    assert got[("CITY-T", "2024-09-01")]["level"] == 2
    daan = got[("TW-63000030", "2023-05-01")]
    assert daan["level"] == 3 and daan["trip_id"] == "" and daan["memory"] == "甲、乙、大安照"
    assert daan["place_name"] == "台灣 / 臺北市 / 大安區"


def V(pid, level, ds="", de="", trip=""):
    return Visit("1", pid, ds, de, level, False, trip, "", "", "manual", "", True)


# ---------- FX1 查核後加的推定修正 ----------

SONGSHAN = Location("C-TWN", tw_county="TW-63000", tw_town="TW-63000010")
HUALIEN = Location("C-TWN", tw_county="TW-10015", tw_town="TW-10015010")
SYD = Location("C-AUS", city="CITY-SYD")
MUC = Location("C-DEU", city="CITY-M")


@pytest.fixture
def more_places(stub_places):
    extra = [Place("TW-63000010", "tw_town", "Songshan", "松山區", parent="TW-63000"),
             Place("TW-10015010", "tw_town", "Hualien City", "花蓮市", parent="TW-10015"),
             Place("CITY-SYD", "city", "Sydney", "雪梨", parent="C-AUS"),
             Place("C-DEU", "country", "Germany", "德國", continent="EU"),
             Place("CITY-M", "city", "Munich", "慕尼黑", parent="C-DEU")]
    return {**stub_places, **{p.id: p for p in extra}}


def test_review_only_at_home_capped_at_2(more_places):
    loc = StubLocator({2: DAAN})
    rows, _ = build_candidates([O(date(2023, 5, 1), 2), O(date(2023, 5, 2), 2)], loc, more_places, [], 3)
    assert rows[0]["level"] == 2 and "只有評論" in rows[0]["evidence"]


def test_home_county_multi_day_not_overnight(more_places):
    loc = StubLocator({2: DAAN})
    home = [V("TW-63000010", 5)]  # 住松山（沒日期＝一直）
    obs = [O(date(2023, 5, 1), 2, "photo", "a"), O(date(2023, 5, 2), 2, "photo", "b")]
    rows, _ = build_candidates(obs, loc, more_places, home, 3)
    assert rows[0]["level"] == 3 and "住家所在縣市" in rows[0]["evidence"]


def test_review_while_living_abroad_clears_date(more_places):
    loc = StubLocator({2: DAAN})
    abroad = [V("CITY-SYD", 5, "2016-02", "2018-11")]
    rows, _ = build_candidates([O(date(2017, 3, 1), 2, label="水電行")], loc, more_places, abroad, 3)
    r = rows[0]
    assert (r["date_start"], r["confidence"]) == ("", "低")
    assert "非到訪日" in r["evidence"] and "到府" in r["evidence"]


def test_same_day_multi_county_reviews_low_confidence(more_places):
    loc = StubLocator({2: DAAN, 3: HUALIEN})
    rows, _ = build_candidates([O(date(2016, 1, 23), 2), O(date(2016, 1, 23), 3)], loc, more_places, [], 3)
    assert all(r["confidence"] == "低" and "跨縣市" in r["evidence"] for r in rows)


def test_no_coordinate_review_skipped(more_places):
    obs = [Observation("review", date(2017, 7, 5), None, None, "Service Example", "u", "AU")]
    rows, stats = build_candidates(obs, StubLocator({}), more_places, [], 3)
    assert rows == [] and stats["no_coordinates"] == 1


def test_long_stay_merged(more_places):
    loc = StubLocator({4: MUC})
    obs = [O(date(2013, 9, 12), 4), O(date(2013, 11, 20), 4), O(date(2014, 3, 7), 4)]
    rows, _ = build_candidates(obs, loc, more_places, [], 3)
    assert len(rows) == 1
    r = rows[0]
    assert (r["date_start"], r["date_end"]) == ("2013-09-12", "2014-03-07") and "可能住過" in r["evidence"]


def test_abroad_candidate_attached_to_long_trip(more_places):
    loc = StubLocator({5: SYD})
    living = [V("CITY-SYD", 5, "2016-02", "2018-11", trip="T-SYD")]
    rows, _ = build_candidates([O(date(2017, 10, 20), 5, "photo", "x")], loc,
                               {**more_places, "CITY-R": Place("CITY-R", "city", "Wollongong", "", parent="C-AUS")}, living, 3)
    # 雪梨本身已被「住過」涵蓋 → 不出候選；換成同國另一城市就掛到 T-SYD
    assert rows == []
    loc2 = StubLocator({6: Location("C-AUS", city="CITY-R")})
    rows, _ = build_candidates([O(date(2017, 10, 20), 6, "photo", "x")], loc2,
                               {**more_places, "CITY-R": Place("CITY-R", "city", "Wollongong", "", parent="C-AUS")}, living, 3)
    assert rows[0]["trip_id"] == "T-SYD"


def test_crossings_mark_home_reviews_while_abroad(more_places):
    loc = StubLocator({2: DAAN, 4: MUC})
    crossings = [("2013-09-04", "2014-04-26")]
    rows, _ = build_candidates([O(date(2013, 11, 1), 2, label="遠端評論"), O(date(2012, 3, 1), 4)],
                               loc, more_places, [], 3, crossings=crossings)
    by = {r["place_id"]: r for r in rows}
    assert by["TW-63000030"]["date_start"] == "" and "非到訪日" in by["TW-63000030"]["evidence"]
    # 國外候選不在任何出入境期間 → 信心低
    assert by["CITY-M"]["confidence"] == "低" and "沒有這段出國" in by["CITY-M"]["evidence"]


def test_load_crossings(tmp_path):
    from lifemap.data import load_crossings
    p = tmp_path / "border_crossings.csv"
    p.write_text("exit_date,entry_date,destination,note\n2013-09-04,2014-04-26,C-DEU,\n", encoding="utf-8-sig")
    assert load_crossings(p) == [("2013-09-04", "2014-04-26")]
    assert load_crossings(tmp_path / "none.csv") == []
    p.write_text("exit_date,entry_date\n2014-04-26,2013-09-04\n", encoding="utf-8")
    with pytest.raises(DataError, match="第 2 列"):
        load_crossings(p)


def test_photo_local_time_stored_as_utc(tmp_path):
    zp = tmp_path / "t.zip"
    # 拍攝 23:30（被當 UTC 存）晚於上傳時間 → 不加時差，仍是同一天
    _make_zip(zp, [], {"p.jpg": {"photoTakenTime": {"timestamp": "1463527800"},  # 2016-05-17 23:30 UTC
                                 "creationTime": {"timestamp": "1463497200"},
                                 "geoDataExif": {"latitude": 25.0, "longitude": 121.5}}})
    [o] = read_takeout(zp)
    assert o.day == date(2016, 5, 17)


def test_covered_rules():
    assert covered([V("X", 4, "2024-03")], "X", 4, "2024-03-10", "2024-03-12")
    assert covered([V("X", 5)], "X", 2, "2019-01-01", "")              # 沒記日期的住過涵蓋全部
    assert not covered([V("X", 3, "2024-03")], "X", 4, "2024-03-10", "")  # 等級較低 → 還是要提
    assert not covered([V("X", 4, "2023")], "X", 4, "2024-03-10", "")     # 不同年 → 新的一趟


def test_skip_already_covered(stub_places):
    loc = StubLocator({1: TOKYO})
    rows, stats = build_candidates([O(date(2024, 3, 10), 1)], loc, stub_places,
                                   [V("CITY-T", 4, "2024-03-10", "2024-03-15")], gap_days=3)
    assert rows == [] and stats["covered"] == 1


# ---------- 確認表 ----------

def _cand(vid, pid="C-JPN", ds="2024-03-10", level=2, photo=""):
    return {"visit_id": vid, "place_id": pid, "date_start": ds, "date_end": "", "level": level,
            "together": "false", "trip_id": "A-JPN-202403", "memory": "auto", "photo": photo, "source": "review",
            "confidence": "低", "confirmed": "false", "place_name": "日本", "evidence": "評論 1、照片 0",
            "decision": ""}


def test_merge_keeps_user_edits(tmp_path):
    p = tmp_path / "pending.csv"
    merge_pending(p, [_cand("P1"), _cand("P2", ds="2024-04-01"), _cand("P3", ds="2024-05-01")])
    rows = read_rows(p)
    rows[0].update(decision="y", level="4", memory="我改的")
    rows[1].update(decision="n")
    write_rows(p, PENDING_FIELDS, rows)
    merged = merge_pending(p, [_cand("P1"), _cand("P3", ds="2024-05-01")])  # P2 這次沒產生
    by = {r["visit_id"]: r for r in merged}
    assert by["P1"]["decision"] == "y" and by["P1"]["level"] == "4" and by["P1"]["memory"] == "我改的"
    assert by["P2"]["decision"] == "n"  # 不收的留著，之後不會再冒出來
    assert "﻿" == p.read_text(encoding="utf-8")[0]  # Excel 要 BOM


def test_merge_refreshes_undecided_rows(tmp_path):
    p = tmp_path / "pending.csv"
    merge_pending(p, [_cand("P1", level=2)])
    merged = merge_pending(p, [_cand("P1", level=4)])  # 規則改了、推定變 4；使用者還沒決定 → 用新的
    assert merged[0]["level"] == 4


def test_apply_pending(tmp_path, places):
    data = tmp_path
    (data / "visits.csv").write_text(
        "visit_id,place_id,date_start,date_end,level,together,trip_id,memory,photo,source,confidence,confirmed\n"
        "1,C-TWN,,,5,false,,家,,manual,高,true\n", encoding="utf-8")
    zp = tmp_path / "t.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("Takeout/地圖/相片和影片/a.jpg", b"JPG")
    rows = [{**_cand("P1", photo=f"zip:{zp}!Takeout/地圖/相片和影片/a.jpg"), "decision": "y", "together": "是"},
            {**_cand("P2", pid="C-AUS"), "decision": "n"},
            {**_cand("P3", pid="C-AUS"), "decision": ""}]
    write_rows(data / "pending.csv", PENDING_FIELDS, rows)
    r = apply_pending(data, places)
    assert r == {"accepted": 1, "kept": 2, "new_trips": 1}
    vs = load_visits(data / "visits.csv", places)
    new = vs[-1]
    assert (new.visit_id, new.place_id, new.confirmed, new.together, new.photo) == \
        ("2", "C-JPN", True, True, "photos/a.jpg")
    assert (data / "photos" / "a.jpg").read_bytes() == b"JPG"
    trips = read_rows(data / "trips.csv")
    assert trips[0]["trip_id"] == "A-JPN-202403" and trips[0]["name"] == "日本 2024-03（自動）"
    assert {x["visit_id"] for x in read_rows(data / "pending.csv")} == {"P2", "P3"}


def test_apply_rejects_bad_decision(tmp_path, places):
    (tmp_path / "visits.csv").write_text(
        "visit_id,place_id,date_start,date_end,level,together,trip_id,memory,photo,source,confidence,confirmed\n",
        encoding="utf-8")
    write_rows(tmp_path / "pending.csv", PENDING_FIELDS, [{**_cand("P1"), "decision": "好"}])
    with pytest.raises(DataError, match="decision"):
        apply_pending(tmp_path, places)
