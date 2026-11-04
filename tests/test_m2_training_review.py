r"""M2-a 查核後補的測試：跨年、邊界（每組一筆剛好達標、一筆差一點）、涵蓋率、同週、先中先贏、ID 重新連結。假資料。"""
from datetime import date, timedelta

import pytest

from _ach import make_domains
from lifemap.ach_pending import apply_judgments, merge_pending
from lifemap.pending import read_rows
from test_m2_training import _src

HDR = "| 日期 | 類別 |\n|---|---|\n"
D0 = date(2026, 1, 5)          # 星期一，也是預設的 week_start


def _rows(dates, cat="羽球"):
    return HDR + "".join(f"| {d} | {cat} |\n" for d in dates)


def _one(tmp_path, text, **over):
    return _src(tmp_path, text, **over).candidates()[0]


def _weekly(n):
    return [(D0 + timedelta(weeks=i)).isoformat() for i in range(n)]


def test_yearless_dates_just_before_week_start_belong_to_previous_year(tmp_path):
    c = _one(tmp_path, _rows(["12/29", "01/05"]))
    assert c["date"] == "2025-12-29"
    assert "2026-01-05" in c["evidence"]


@pytest.mark.parametrize("text,expected", [("01/06", "2026-01-06"), ("01/05", "2027-01-05")])
def test_week_start_minus_14_vs_minus_15(tmp_path, text, expected):
    assert _one(tmp_path, _rows([text]), week_start="2026-01-20")["date"] == expected


def test_weeks_3_vs_2(tmp_path):
    assert _one(tmp_path, _rows(_weekly(3)))["level"] == "2"
    assert _one(tmp_path, _rows(_weekly(2)))["level"] == "1"


@pytest.mark.parametrize("extra,level", [(90, "3"), (89, "2")])
def test_span_90_vs_89_days(tmp_path, extra, level):
    ds = _weekly(12) + [(D0 + timedelta(days=extra)).isoformat()]
    assert _one(tmp_path, _rows(ds))["level"] == level


@pytest.mark.parametrize("extra,level", [(365, "5"), (364, "3")])
def test_span_365_vs_364_days(tmp_path, extra, level):
    ds = _weekly(52) + [(D0 + timedelta(days=extra)).isoformat()]
    assert _one(tmp_path, _rows(ds))["level"] == level


def test_long_span_but_low_coverage_is_not_regular(tmp_path):
    ds = _weekly(3) + [(D0 + timedelta(days=120)).isoformat()]        # 4 週有紀錄 / 期間 18 週
    assert _one(tmp_path, _rows(ds))["level"] == "2"
    assert _one(tmp_path, _rows(ds), min_coverage=0.2)["level"] == "3"


def test_two_records_in_one_week_count_once(tmp_path):
    c = _one(tmp_path, _rows(["2026-01-05", "2026-01-07", "2026-01-11"]))     # 同一週一～日
    assert "共 1 週" in c["evidence"] and c["level"] == "1"
    c = _one(tmp_path, _rows(["2026-01-11", "2026-01-12"]))                   # 週日與下週一是兩週
    assert "共 2 週" in c["evidence"]


def test_item_map_first_key_wins(tmp_path):
    text = HDR + "| 2026-01-05 | 胸肩羽球 |\n"
    a = _one(tmp_path, text, item_map={"羽球": "甲", "胸肩": "乙"})
    b = _one(tmp_path, text, item_map={"胸肩": "乙", "羽球": "甲"})
    assert (a["item"], b["item"]) == ("甲", "乙")


def test_older_records_change_id_but_relink_keeps_judgment(tmp_path):
    pending = tmp_path / "pending_achievements.csv"
    imap = {"羽球": "羽球", "重訓": "重訓"}
    rows = _src(tmp_path, HDR + "| 2026-01-05 | 羽球 |\n| 2026-01-06 | 重訓 |\n", item_map=imap).candidates()
    merge_pending(pending, rows, set())
    old_id = next(r["achievement_id"] for r in rows if r["item"] == "羽球")
    apply_judgments(pending, [{"achievement_id": old_id, "level": 3, "suggest": "y", "reason": "判斷"}],
                    make_domains())
    later = _src(tmp_path, HDR + "| 2025-11-03 | 羽球 |\n| 2026-01-05 | 羽球 |\n| 2026-01-06 | 重訓 |\n",
                 item_map=imap).candidates()
    new_id = next(r["achievement_id"] for r in later if r["item"] == "羽球")
    assert new_id != old_id                                     # 補了更早的紀錄 → 第一次日期變 → ID 變
    merge_pending(pending, later, set())
    got = {r["achievement_id"]: r for r in read_rows(pending)}
    assert old_id not in got and len(got) == 2                  # 同一個檔有兩個項目，仍要連得上
    assert (got[new_id]["suggest"], got[new_id]["reason"]) == ("y", "判斷")


def test_relink_when_two_items_of_same_file_both_change_id(tmp_path):
    pending = tmp_path / "pending_achievements.csv"
    imap = {"羽球": "羽球", "重訓": "重訓"}
    rows = _src(tmp_path, HDR + "| 2026-01-05 | 羽球 |\n| 2026-01-06 | 重訓 |\n", item_map=imap).candidates()
    merge_pending(pending, rows, set())
    ids = {r["item"]: r["achievement_id"] for r in rows}
    apply_judgments(pending, [{"achievement_id": ids["羽球"], "level": 3, "suggest": "y", "reason": "甲"},
                              {"achievement_id": ids["重訓"], "level": 2, "suggest": "n", "reason": "乙"}], make_domains())
    later = _src(tmp_path, HDR + "| 2025-11-03 | 羽球 |\n| 2025-11-04 | 重訓 |\n| 2026-01-05 | 羽球 |\n",
                 item_map=imap).candidates()
    merge_pending(pending, later, set())
    all_rows = read_rows(pending)
    assert len(all_rows) == 2                                   # 舊列要被連到新 ID，不能新舊並存
    got = {r["item"]: r for r in all_rows}
    assert (got["羽球"]["reason"], got["重訓"]["reason"]) == ("甲", "乙")


@pytest.mark.parametrize("text,expected", [("12/22", "2025-12-22"), ("12/21", "2026-12-21")])
def test_previous_year_window_edge(tmp_path, text, expected):
    assert _one(tmp_path, _rows([text]))["date"] == expected          # week_start 2026-01-05，窗口從 12/22 起


@pytest.mark.parametrize("idx,over,level", [
    ([0, 1, 2, 3, 4, 5, 13], {}, "3"),                       # 7/14＝0.5 剛好達標
    ([0, 1, 2, 3, 4, 5, 14], {}, "2"),                       # 7/15 差一點
    ([0, 1, 2, 3, 4, 5, 6, 7, 13], {"min_coverage": 0.6}, "3"),   # 9/14＝0.64 過 0.6
    ([0, 1, 2, 3, 4, 5, 6, 7, 15], {"min_coverage": 0.6}, "2"),   # 9/16＝0.56 不過
])
def test_coverage_uses_inclusive_week_span(tmp_path, idx, over, level):
    ds = [(D0 + timedelta(weeks=i)).isoformat() for i in idx]
    assert _one(tmp_path, _rows(ds), **over)["level"] == level
