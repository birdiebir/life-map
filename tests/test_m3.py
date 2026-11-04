from datetime import date

import pytest

from lifemap.data import Visit
from lifemap.geo import Location
from lifemap.infer import build_candidates
from lifemap.levels import place_levels
from lifemap.recommend import recommend
from lifemap.reference import Place
from lifemap.sets import set_progress
from lifemap.takeout import Observation


@pytest.fixture
def m3(places):
    extra = [
        Place("TW-63000030", "tw_town", "Da'an", "大安區", parent="TW-63000", lat=25.026, lon=121.543),
        Place("TW-63000010", "tw_town", "Songshan", "松山區", parent="TW-63000", lat=25.055, lon=121.560),
        Place("TW-63000100", "tw_town", "Neihu", "內湖區", parent="TW-63000", lat=25.080, lon=121.590),
        Place("TW-10015010", "tw_town", "Hualien City", "花蓮市", parent="TW-10015", lat=23.99, lon=121.60),
        Place("TWP-NP-01", "tw_poi", "", "陽明山國家公園", parent="TW-63000010", lat=25.16, lon=121.55,
              tags=frozenset({"tier1", "national_park"}), radius_km=8),
        Place("TWP-CH-01", "tw_poi", "", "太魯閣", parent="TW-10015010", lat=24.16, lon=121.62,
              tags=frozenset({"tier1", "national_park"}), radius_km=10),
        Place("C-FRA", "country", "France", "法國", continent="EU", tags=frozenset({"un194"})),
        Place("CITY-P", "city", "Paris", "巴黎", parent="C-FRA", lat=48.85, lon=2.35, tags=frozenset({"curated"})),
    ]
    return {**places, **{p.id: p for p in extra}}


def V(pid, level, ds="", together=False, vid="1"):
    return Visit(vid, pid, ds, "", level, together, "", "", "", "manual", "", True)


def test_tagged_sets_and_empty_sets_skipped(m3):
    cfg = [{"id": "np", "name": "國家公園", "kind": "places", "place_kind": "tw_poi", "tag": "tier1"},
           {"id": "whs", "name": "世界遺產", "kind": "places", "place_kind": "whs"},  # 參考資料沒有 → 略過
           {"id": "off", "name": "關掉的", "kind": "places", "place_kind": "tw_poi", "enabled": False}]
    lv = place_levels([V("TWP-NP-01", 3)], m3)
    prog = set_progress(cfg, m3, lv, 2)
    assert [(s["id"], s["done"], s["total"]) for s in prog] == [("np", 1, 2)]
    assert lv["TW-63000010"] == 3  # 景點的等級往上傳到鄉鎮


class PoiLocator:
    def locate(self, lat, lon, hint=None):
        return Location("C-TWN", tw_county="TW-63000", tw_town="TW-63000010")

    def pois_near(self, lat, lon):
        return ["TWP-NP-01"] if lat > 25.1 else []


def test_poi_candidate_generated_alongside_town(m3):
    obs = [Observation("photo", date(2024, 5, 1), 25.16, 121.55, "", "zip:z!a.jpg")]
    rows, _ = build_candidates(obs, PoiLocator(), m3, [], 3)
    assert {r["place_id"] for r in rows} == {"TW-63000010", "TWP-NP-01"}


def test_poi_candidates_merged_into_one(m3):
    obs = [Observation("photo", date(2020, 1, 1), 25.16, 121.55, "", "zip:z!a.jpg"),
           Observation("photo", date(2023, 5, 1), 25.16, 121.55, "", "zip:z!b.jpg"),
           Observation("photo", date(2023, 5, 2), 25.16, 121.55, "", "zip:z!c.jpg")]
    rows, _ = build_candidates(obs, PoiLocator(), m3, [], 3)
    poi = [r for r in rows if r["place_id"] == "TWP-NP-01"]
    assert len(poi) == 1
    assert poi[0]["date_start"] == "2020-01-01" and poi[0]["level"] == 4 and "一共出現 2 次" in poi[0]["evidence"]


def test_area_poi_radius_capped(tmp_path):
    from lifemap.geo import Locator
    import paths
    from lifemap.reference import load_places
    places = load_places(paths.REFERENCE)
    big = Place("TWP-X", "tw_poi", "", "大範圍", parent="TW-63000010", lat=25.0, lon=121.5, radius_km=25)
    loc = Locator(paths.REFERENCE, {**places, "TWP-X": big}, {**paths.config("import"), "poi_max_radius_km": 8})
    assert "TWP-X" in loc.pois_near(25.05, 121.5)       # 約 5.6 km
    assert "TWP-X" not in loc.pois_near(25.15, 121.5)   # 約 16.7 km，超過 8 km 上限


def test_recommendations(m3):
    visits = [V("TW-63000010", 5, "2021-04", vid="1"), V("TW-63000030", 3, vid="2"),
              V("TW-10015010", 3, vid="3"), V("TWP-CH-01", 2, vid="4")]
    lv = place_levels(visits, m3)
    lv_t = place_levels([], m3)
    sets_cfg = [{"id": "tw_towns", "name": "鄉鎮", "kind": "places", "place_kind": "tw_town"},
                {"id": "countries", "name": "國家", "kind": "places", "place_kind": "country"}]
    prog = set_progress(sets_cfg, m3, lv, 2)
    recs = {s["title"]: s["items"] for s in recommend(m3, lv, lv_t, prog, sets_cfg, visits, {})}
    # 家＝最近開始住的松山區；陽明山在 150 km 內、還沒去
    assert [i["pid"] for i in recs["週末就能去"]] == ["TWP-NP-01"]
    # 鄉鎮完成 3/4 ≥ 一半 → 快完成；缺的內湖有座標可推
    assert recs["快完成的套組"][0]["pid"] == "TW-63000100"
    # 同一個地方不重複出現（內湖不會再出現在「順路收集鄉鎮」）
    assert "順路收集鄉鎮" not in recs or all(i["pid"] != "TW-63000100" for i in recs["順路收集鄉鎮"])
    # 國家套組 1/6 不到一半，且國家沒座標 → 不會推不丹之類
    assert all(not i["pid"].startswith("C-") for items in recs.values() for i in items)
    assert recs["值得再深玩"][0]["pid"] == "TWP-CH-01"
    assert recs["下一個國外目標"][0]["pid"] == "CITY-P"
    assert {i["pid"] for i in recs["還沒一起去過"]} >= {"TW-10015"}  # 一起去過的建議以縣市為單位


def test_settings_home_overrides(m3):
    visits = [V("TW-63000010", 5, "2021-04")]
    lv = place_levels(visits, m3)
    recs = recommend(m3, lv, {}, [], [], visits, {"home_place": "TW-10015010"})
    weekend = next(s for s in recs if s["title"] == "週末就能去")
    assert weekend["items"][0]["pid"] == "TWP-CH-01"  # 家改在花蓮 → 太魯閣最近
