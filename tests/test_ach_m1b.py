r"""M1b：重匯入保留修改、跨來源去重複、apply 報 ID、只有年份排序、個人套組、判斷欄位與 apply_judgments。"""
from __future__ import annotations

import json

import pytest

from _ach import ach, make_domains, real_domains, row, write_ach
from lifemap.ach_pending import (PENDING_FIELDS, apply_judgments, apply_pending, merge_pending)
from lifemap.ach_sources import dedupe_across
from lifemap.ach_stats import by_year, visible_cards
from lifemap.achievements import load_domains_for
from lifemap.data import DataError
from lifemap.pending import read_rows, write_rows


def cand(i, title="候選", **kw):
    r = {f: "" for f in PENDING_FIELDS}
    r.update(achievement_id=i, domain="learning", item="A", title=title, date="2024-01", origin="csv",
             confirmed="false", together="false", suppressed="false", evidence="e")
    r.update(kw)
    return r


# a. 重匯入保留
def test_reimport_keeps_title_date_domain_confidence_suggest_reason(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    write_rows(p, PENDING_FIELDS, [cand("A-1", title="我改的標題", date="2023-05", domain="career",
                                        confidence="高", suggest="y", reason="L4：獲獎")])
    merge_pending(p, [cand("A-1")], set())
    r = read_rows(p)[0]
    assert (r["title"], r["date"], r["domain"], r["confidence"]) == ("我改的標題", "2023-05", "career", "高")
    assert (r["suggest"], r["reason"]) == ("y", "L4：獲獎")


def test_old_pending_without_new_columns_readable(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    old_fields = [f for f in PENDING_FIELDS if f not in ("suggest", "reason")]
    write_rows(p, old_fields, [{**cand("A-1"), "decision": "y"}])
    merged = merge_pending(p, [cand("A-1")], set())
    assert merged[0]["decision"] == "y"


# b. 跨來源去重複
def test_dedupe_across_normalizes_title_and_date():
    a = cand("A-1", title="碩士 畢業!", date="2019-07")
    b = cand("A-2", title="碩士畢業", date="2019-07")
    c = cand("A-3", title="碩士畢業", date="2019-08")
    d = cand("A-4", title="MASTER Graduation", date="2019-07")
    e = cand("A-5", title="master  graduation", date="2019-07")
    out = dedupe_across([a, b, c, d, e])
    assert [r["achievement_id"] for r in out] == ["A-1", "A-3", "A-4"]


# c. apply 錯誤報 ID
def test_apply_error_reports_achievement_id(tmp_path):
    d = make_domains()
    write_ach(tmp_path, [row("ok-1")])
    write_rows(tmp_path / "pending_achievements.csv", PENDING_FIELDS,
               [cand("A-bad", decision="y", domain="nope")])
    with pytest.raises(DataError) as e:
        apply_pending(tmp_path, d)
    assert "A-bad" in str(e.value) and "第 3 列" not in str(e.value)


# d. 只有年份排後面
def test_year_only_sorted_after_dated_same_year():
    achs = [ach("y", date="2024"), ach("m", date="2024-06"), ach("d", date="2024-03-05"), ach("n", date="2023")]
    assert [a.achievement_id for a in visible_cards(achs, [])] == ["n", "d", "m", "y"]
    assert [a.achievement_id for a in by_year(achs, [])["2024"]] == ["d", "m", "y"]


# e. 個人套組
def test_load_domains_for_merges_private_sets(tmp_path):
    (tmp_path / "achievement_sets.json").write_text(json.dumps({"learning": [
        {"id": "learning_cert", "name": "我的證照", "items": ["X1", "X2"]},
        {"id": "my_new", "name": "新套組", "items": ["Z"]}]}), encoding="utf-8")
    d = load_domains_for(tmp_path)
    sets = {s.id: s for s in d.by_id["learning"].sets}
    assert sets["learning_cert"].items == ("X1", "X2") and sets["learning_cert"].name == "我的證照"
    assert "my_new" in sets and "learning_school" in sets


def test_load_domains_for_without_file_uses_generic(tmp_path):
    d = load_domains_for(tmp_path)
    items = {i for s in d.by_id["learning"].sets for i in s.items}
    assert "語言檢定" in items and "證照甲" not in items and "樂器乙" not in items


def test_load_domains_set_missing_fields_collected_as_data_error(tmp_path):
    (tmp_path / "achievement_sets.json").write_text(json.dumps({"learning": [
        {"id": "s1", "items": ["X"]}, {"name": "沒 id", "items": []}, {"id": "s3", "name": "沒 items"}]}),
        encoding="utf-8")
    with pytest.raises(DataError) as e:
        load_domains_for(tmp_path)
    msg = str(e.value)
    assert "KeyError" not in msg and msg.count("套組缺 id／name／items") == 3


# 先去雜訊、再去重複
def test_filter_candidates_denoise_before_dedupe():
    import sys
    from _ach import ROOT
    sys.path.insert(0, str(ROOT / "scripts"))
    from import_achievements import filter_candidates
    # 雜訊筆排前面，標題正規化後跟好的那筆相同；舊順序（先去重複）會留下雜訊筆、再被規則擋掉，兩筆都沒了
    noise = cand("N", title="碩士 畢業!", origin="kb_note", date="2019-07")
    good = cand("G", title="碩士畢業", origin="kb_note", date="2019-07")
    rules = {"noise": {"apply_to_origins": ["kb_note"], "min_title_chars": 0, "drop_title_patterns": ["!$"],
                       "require_signal": False, "signals": []}, "item_rules": []}
    out, dropped, n_denoised = filter_candidates([noise, good], rules)
    assert [r["achievement_id"] for r in out] == ["G"] and n_denoised == 1 and sum(dropped.values()) == 1


def test_load_domains_for_unknown_domain_in_sets_error(tmp_path):
    (tmp_path / "achievement_sets.json").write_text(json.dumps({"nope": []}), encoding="utf-8")
    with pytest.raises(DataError):
        load_domains_for(tmp_path)


# 3. apply_judgments
def _setup(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    write_rows(p, PENDING_FIELDS, [cand("A-1"), cand("A-2", decision="n"), cand("A-3")])
    return p


def test_old_judgments_write_pending_only(tmp_path):
    d = make_domains()
    p = _setup(tmp_path)
    res = apply_judgments(p, [{"achievement_id": "A-1", "level": 4, "suggest": "y", "reason": "獲獎",
                               "item": "新項目", "title": "新標題", "confidence": "高"},
                              {"achievement_id": "A-2", "level": 1, "suggest": "n", "reason": "x"}], d)
    assert res["applied"] == 1 and res["skipped_decided"] == 1
    rows = {r["achievement_id"]: r for r in read_rows(p)}
    assert (rows["A-1"]["level"], rows["A-1"]["suggest"], rows["A-1"]["reason"]) == ("4", "y", "獲獎")
    assert (rows["A-1"]["item"], rows["A-1"]["title"], rows["A-1"]["confidence"]) == ("新項目", "新標題", "高")
    assert rows["A-2"]["level"] == "" and rows["A-1"]["decision"] == ""
    assert not (tmp_path / "achievements.csv").exists()


@pytest.mark.parametrize("bad", [
    {"achievement_id": "NOPE", "level": 1, "suggest": "y", "reason": ""},
    {"achievement_id": "A-1", "level": 6, "suggest": "y", "reason": ""},
    {"achievement_id": "A-1", "level": "x", "suggest": "y", "reason": ""},
    {"achievement_id": "A-1", "level": 1, "suggest": "maybe", "reason": ""},
    {"achievement_id": "A-1", "level": 1, "suggest": "y", "reason": "", "domain": "nope"},
])
def test_judgments_validation_all_or_nothing(tmp_path, bad):
    d = make_domains()
    p = _setup(tmp_path)
    before = p.read_bytes()
    good = {"achievement_id": "A-3", "level": 2, "suggest": "n", "reason": "ok"}
    with pytest.raises(DataError):
        apply_judgments(p, [good, bad], d)
    assert p.read_bytes() == before


@pytest.mark.parametrize("lv", [3.7, "3.7", True, False, None, "", "x", -1, "-1"])
def test_judgments_level_must_be_integer(tmp_path, lv):
    d = make_domains()
    p = _setup(tmp_path)
    before = p.read_bytes()
    with pytest.raises(DataError):
        apply_judgments(p, [{"achievement_id": "A-1", "level": lv, "suggest": "y", "reason": ""}], d)
    assert p.read_bytes() == before


def test_judgments_level_numeric_string_ok(tmp_path):
    d = make_domains()
    p = _setup(tmp_path)
    apply_judgments(p, [{"achievement_id": "A-1", "level": "3", "suggest": "y", "reason": ""}], d)
    assert {r["achievement_id"]: r for r in read_rows(p)}["A-1"]["level"] == "3"


def test_judgments_duplicate_id_error(tmp_path):
    d = make_domains()
    p = _setup(tmp_path)
    before = p.read_bytes()
    j = {"achievement_id": "A-1", "level": 2, "suggest": "y", "reason": ""}
    with pytest.raises(DataError) as e:
        apply_judgments(p, [j, {**j, "level": 3}, {"achievement_id": "NOPE", "level": 9, "suggest": "y"}], d)
    msg = str(e.value)
    assert "不只一次" in msg and "NOPE" in msg and "有 2 筆" in msg  # 全部錯誤一次列出
    assert p.read_bytes() == before


def test_judgments_errors_listed_together(tmp_path):
    d = make_domains()
    p = _setup(tmp_path)
    with pytest.raises(DataError) as e:
        apply_judgments(p, [{"achievement_id": "NOPE", "level": 9, "suggest": "q", "reason": ""}], d)
    msg = str(e.value)
    assert "NOPE" in msg and "0～5" in msg and "y" in msg


def test_apply_judgments_script_dry_run_then_write(tmp_path):
    import subprocess
    import sys
    from _ach import ROOT
    _setup(tmp_path)
    j = tmp_path / "j.json"
    j.write_text(json.dumps([{"achievement_id": "A-1", "level": 3, "suggest": "y", "reason": "r"}]), encoding="utf-8")
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "apply_judgments.py"), str(j), "--data-dir", str(tmp_path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert read_rows(tmp_path / "pending_achievements.csv")[0]["level"] == ""
    r = subprocess.run(cmd + ["--write"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert read_rows(tmp_path / "pending_achievements.csv")[0]["level"] == "3"
