from lifemap.data import Visit
from lifemap.levels import ancestors, place_levels
from lifemap.sets import scores, set_progress


def V(pid, level, together=False, confirmed=True, vid="1"):
    return Visit(vid, pid, "", "", level, together, "", "", "", "manual", "", confirmed)


def test_ancestors(places):
    assert ancestors("TW-63000030", places) == ["TW-63000", "C-TWN"]
    assert ancestors("C-JPN", places) == []


def test_levels_propagate_up_and_take_max(places):
    lv = place_levels([V("CITY-1", 4), V("C-JPN", 2, vid="2"), V("TW-63000030", 5, vid="3")], places)
    assert lv["CITY-1"] == 4 and lv["C-JPN"] == 4
    assert lv["TW-63000030"] == 5 and lv["TW-63000"] == 5 and lv["C-TWN"] == 5
    assert "TW-63000010" not in lv


def test_unconfirmed_excluded_by_default(places):
    vs = [V("C-AUS", 3, confirmed=False)]
    assert place_levels(vs, places) == {}
    assert place_levels(vs, places, include_unconfirmed=True)["C-AUS"] == 3


def test_together_only(places):
    vs = [V("CITY-2", 5), V("C-JPN", 3, together=True, vid="2")]
    lv = place_levels(vs, places, together_only=True)
    assert lv == {"C-JPN": 3}


SETS = [
    {"id": "countries", "name": "國家／地區", "kind": "places", "place_kind": "country"},
    {"id": "continents", "name": "七大洲", "kind": "continents"},
    {"id": "tw_towns", "name": "鄉鎮", "kind": "places", "place_kind": "tw_town"},
]


def test_set_progress_respects_min_level(places):
    lv = place_levels([V("CITY-1", 1), V("C-AUS", 3, vid="2"), V("C-XKX", 2, vid="3"),
                       V("TW-63000030", 5, vid="4")], places)
    prog = {s["id"]: s for s in set_progress(SETS, places, lv, min_level=2)}
    # 日本只有轉機（1 級）不算去過；科索沃地圖上沒形狀也照算
    assert prog["countries"]["done"] == 3 and prog["countries"]["total"] == 4
    assert set(prog["countries"]["members_done"]) == {"C-AUS", "C-XKX", "C-TWN"}
    assert prog["continents"]["done"] == 3 and prog["continents"]["total"] == 7
    assert (prog["tw_towns"]["done"], prog["tw_towns"]["total"]) == (1, 2)


def test_scores_sum_levels_by_kind(places):
    lv = place_levels([V("CITY-1", 4), V("TW-63000030", 5, vid="2")], places)
    s = scores({"world": ["country", "city"], "taiwan": ["tw_county", "tw_town"]}, places, lv)
    assert s == {"world": 4 + 4 + 5, "taiwan": 5 + 5}
