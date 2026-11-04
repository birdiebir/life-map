"""M1c-C 審查修正：重新連結、空白與布林正規化、使用者刪列、旁檔格式異常。"""
from __future__ import annotations

import json

from _ach import make_domains
from lifemap.ach_pending import PENDING_FIELDS, apply_judgments, merge_pending, sidecar_path
from lifemap.pending import read_rows, write_rows
from test_m1c_reimport import P, cand, one, side


def ids(p):
    return {r["achievement_id"] for r in read_rows(p)}


def test_relink_when_title_changes_carries_judged_and_user_edit(tmp_path, capsys):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", source="n.md:5", level="")], set())
    apply_judgments(p, [{"achievement_id": "A-1", "level": 3, "suggest": "y", "reason": "因為"}], make_domains())
    rows = read_rows(p)
    rows[0]["memory"] = "手改回憶"
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-2", source="n.md:5", title="改字後", level="")], set())
    assert ids(p) == {"A-2"} and "A-1" not in side(p)
    r = one(p, "A-2")
    assert (r["level"], r["suggest"], r["memory"], r["title"]) == ("3", "y", "手改回憶", "改字後")
    assert side(p)["A-2"]["judged"]["level"] == "3" and side(p)["A-2"]["src"]["title"] == "改字後"
    assert "ID 換了：A-1 → A-2（改字後）" in capsys.readouterr().out


def test_no_relink_when_line_number_changes_keeps_old_with_warning(tmp_path, capsys):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", source="n.md:5", level="")], set())
    apply_judgments(p, [{"achievement_id": "A-1", "level": 2, "suggest": "n"}], make_domains())
    merge_pending(p, [cand("A-2", source="n.md:7", title="別的")], set())
    assert ids(p) == {"A-1", "A-2"}
    assert "來源已不再產生，保留：A-1" in capsys.readouterr().err
    assert "A-1" in side(p)


def test_untouched_stale_row_dropped(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", source="n.md:5")], set())
    merge_pending(p, [cand("A-2", source="n.md:9")], set())
    assert ids(p) == {"A-2"}


def test_ambiguous_relink_is_not_done(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", source="n.md:5", level=""),
                      cand("A-2", source="n.md:5", title="另一個", level="")], set())
    apply_judgments(p, [{"achievement_id": "A-1", "level": 3, "suggest": "y"}], make_domains())
    merge_pending(p, [cand("B-1", source="n.md:5", title="新")], set())      # 兩個舊候選 → 不連結
    assert ids(p) == {"B-1", "A-1"}                                          # A-1 有判斷值留著，A-2 沒動過丟掉


def test_decided_row_not_relinked(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", source="n.md:5")], set())
    rows = read_rows(p)
    rows[0]["decision"] = "y"
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-2", source="n.md:5", title="改字")], set())
    assert ids(p) == {"A-1", "A-2"}
    assert one(p, "A-1")["decision"] == "y" and one(p, "A-2")["decision"] == ""


def test_trailing_whitespace_not_treated_as_edit(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", title="標題 ", evidence="證據 ")], set())
    assert side(p)["A-1"]["src"]["title"] == "標題"
    merge_pending(p, [cand("A-1", title="標題 ", evidence="新證據")], set())
    assert one(p)["evidence"] == "新證據"                      # 沒被誤判成使用者改過


def test_bool_spelling_not_treated_as_edit(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", together="false", suppressed="false")], set())
    rows = read_rows(p)
    rows[0]["together"] = "FALSE"
    rows[0]["suppressed"] = "0"
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", together="true", suppressed="true")], set())
    r = one(p)
    assert r["together"] == "true" and r["suppressed"] == "true"      # 只是寫法不同，跟著來源


def test_bool_real_change_kept(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", together="false")], set())
    rows = read_rows(p)
    rows[0]["together"] = "TRUE"
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", together="false")], set())
    assert one(p)["together"] == "TRUE"


def test_row_deleted_in_excel_then_regenerated_keeps_judged(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", level="")], set())
    apply_judgments(p, [{"achievement_id": "A-1", "level": 3, "suggest": "y", "reason": "因為"}], make_domains())
    write_rows(p, PENDING_FIELDS, [])
    merge_pending(p, [cand("A-1", level="")], set())
    r = one(p)
    assert (r["level"], r["suggest"], r["reason"]) == ("3", "y", "因為")
    assert side(p)["A-1"]["judged"]["level"] == "3"


def test_manual_origin_case_and_space_insensitive(tmp_path):
    p = P(tmp_path)
    write_rows(p, PENDING_FIELDS, [cand("M-1", origin=" Manual ")])
    merge_pending(p, [cand("A-1")], set())
    assert "M-1" in ids(p)


def test_judged_not_dict_treated_empty_with_warning(tmp_path, capsys):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1")], set())
    d = side(p)
    d["A-1"]["judged"] = "壞的"
    sidecar_path(p).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    merge_pending(p, [cand("A-1", evidence="e9")], set())
    assert one(p)["evidence"] == "e9" and side(p)["A-1"]["judged"] == {}
    assert "judged" in capsys.readouterr().err


def test_decision_cleared_again_keeps_previous_values(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1")], set())
    rows = read_rows(p)
    rows[0].update(decision="y", memory="決定時的回憶")
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", evidence="e2")], set())
    rows = read_rows(p)
    rows[0]["decision"] = ""
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", evidence="e3")], set())
    r = one(p)
    assert r["memory"] == "決定時的回憶" and r["decision"] == "" and r["evidence"] == "e1"   # 決定時看到的版本，不被來源蓋掉


def test_apply_judgments_with_corrupt_sidecar_does_not_overwrite_it(tmp_path):
    p = P(tmp_path)
    write_rows(p, PENDING_FIELDS, [cand("A-1", level="")])
    sidecar_path(p).write_text("{壞掉", encoding="utf-8")
    r = apply_judgments(p, [{"achievement_id": "A-1", "level": 2, "suggest": "y"}], make_domains())
    assert r["applied"] == 1 and one(p)["level"] == "2"
    assert sidecar_path(p).read_text(encoding="utf-8") == "{壞掉"
