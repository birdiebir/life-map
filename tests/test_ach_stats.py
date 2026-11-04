"""Task 2：項目等級、經驗值、套組格子、雷達、依年份、卡牆、最近一張卡。"""
from _ach import ach, make_domains
from lifemap.ach_stats import by_year, domain_xp, item_levels, latest_card, radar, set_grid, visible_cards


def test_unconfirmed_not_counted_by_default():
    achs = [ach("1", level=3), ach("2", item="B", level=4, confirmed=False)]
    assert item_levels(achs) == {("learning", "A"): 3}
    assert item_levels(achs, include_unconfirmed=True)[("learning", "B")] == 4


def test_together_only():
    achs = [ach("1", level=3, together=True), ach("2", item="B", level=4, together=False)]
    assert item_levels(achs, together_only=True) == {("learning", "A"): 3}


def test_item_level_is_max():
    achs = [ach("1", level=2), ach("2", level=4), ach("3", level=3)]
    assert item_levels(achs)[("learning", "A")] == 4


def test_xp_uses_score_table_and_domains_separate():
    achs = [ach("1", item="A", level=2), ach("2", item="B", level=3), ach("3", domain="sports", item="S", level=1)]
    d = make_domains()
    assert domain_xp(item_levels(achs), d) == {"learning": 5, "sports": 1}
    d2 = make_domains(scores={"0": 0, "1": 10, "2": 20, "3": 30, "4": 40, "5": 50})  # 改分數表結果會變
    assert domain_xp(item_levels(achs), d2) == {"learning": 50, "sports": 10}


def test_xp_empty_domain_is_zero():
    assert domain_xp({}, make_domains()) == {"learning": 0, "sports": 0}


def test_set_grid_names_for_locked_cells_and_zero_for_missing():
    grid = set_grid(make_domains(), item_levels([ach("1", item="A", level=3), ach("2", item="B", level=0)]))
    s = grid["learning"][0]
    assert (s["done"], s["total"]) == (1, 3)
    assert [c["item"] for c in s["cells"]] == ["A", "B", "C"]
    assert [c["level"] for c in s["cells"]] == [3, 0, 0]
    assert [c["unlocked"] for c in s["cells"]] == [True, False, False]
    assert grid["sports"] == []


def test_set_grid_min_level_threshold():
    d = make_domains(min_level=3)
    s = set_grid(d, item_levels([ach("1", item="A", level=2), ach("2", item="B", level=3)]))["learning"][0]
    assert s["done"] == 1


def test_radar_top5_average_pads_zero():
    achs = [ach(str(i), item=f"I{i}", level=lv) for i, lv in enumerate([5, 4, 3], start=1)]
    r = radar(item_levels(achs), make_domains())
    assert r["learning"] == (5 + 4 + 3) / 5      # 不足 5 項補 0
    assert r["sports"] == 0


def test_radar_many_items_not_bigger():
    achs = [ach(str(i), item=f"I{i}", level=3) for i in range(6)]
    few = [ach(str(i), item=f"I{i}", level=3) for i in range(5)]
    assert radar(item_levels(achs), make_domains())["learning"] == 3.0   # 6 項全 3 級＝3.0
    assert radar(item_levels(few), make_domains())["learning"] == 3.0


def test_radar_picks_top_n_only():
    achs = [ach(str(i), item=f"I{i}", level=lv) for i, lv in enumerate([5, 5, 5, 5, 5, 1, 1], start=1)]
    assert radar(item_levels(achs), make_domains())["learning"] == 5.0


def test_suppressed_still_counts_but_hidden_from_cards():
    hidden = ach("1", item="A", level=5, suppressed=True, date="2020-05")
    shown = ach("2", item="B", level=2, date="2021-01")
    achs = [hidden, shown]
    d = make_domains()
    lv = item_levels(achs)
    assert lv[("learning", "A")] == 5                       # 等級照算
    assert domain_xp(lv, d)["learning"] == 7                # 經驗值照算
    assert radar(lv, d)["learning"] == (5 + 2) / 5          # 雷達照算
    assert [a.achievement_id for a in visible_cards(achs, [])] == ["2"]
    assert by_year(achs, []) == {"2021": [shown]}
    assert latest_card(achs, [], "learning") is shown


def test_rule_based_suppression_hides_cards():
    a = ach("1", item="A", level=4, date="2020-05")
    b = ach("2", item="B", level=2, date="2022-01")
    rules = [{"domain": "learning", "item": "A"}]
    assert [x.achievement_id for x in visible_cards([a, b], rules)] == ["2"]
    assert latest_card([a], rules, "learning") is None
    rules = [{"date_from": "2022-01", "date_to": "2022-12"}]
    assert [x.achievement_id for x in visible_cards([a, b], rules)] == ["1"]
    assert list(by_year([a, b], rules)) == ["2020"]


def test_by_year_groups_sorted_undated_last_and_skips_unconfirmed():
    a = ach("1", date="2021-03")
    b = ach("2", item="B", date="2018")
    c = ach("3", item="C", date="")
    u = ach("4", item="D", date="2019", confirmed=False)
    y = by_year([a, b, c, u], [])
    assert list(y) == ["2018", "2021", ""]
    assert y["2021"] == [a]


def test_latest_card_by_domain_and_date():
    a = ach("1", date="2020-01")
    b = ach("2", item="B", date="2023-06-02")
    c = ach("3", domain="sports", item="S", date="2024")
    assert latest_card([a, b, c], [], "learning") is b
    assert latest_card([a, b, c], [], "sports") is c
    assert latest_card([a], [], "sports") is None
