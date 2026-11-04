"""M1c-C：重匯入保護（旁檔 pending_achievements.auto.json）。"""
from __future__ import annotations

import json

from _ach import make_domains, row, write_ach
from lifemap.ach_pending import PENDING_FIELDS, apply_judgments, apply_pending, merge_pending, sidecar_path
from lifemap.pending import read_rows, write_rows


def cand(i, **kw):
    r = {f: "" for f in PENDING_FIELDS}
    r.update(achievement_id=i, domain="learning", item="A", title="原標題", date="2024-01", origin="kb_note",
             confirmed="false", together="false", suppressed="false", source="s:1", evidence="e1", confidence="中")
    r.update(kw)
    return r


def P(tmp_path):
    return tmp_path / "pending_achievements.csv"


def side(p):
    return json.loads(sidecar_path(p).read_text(encoding="utf-8"))


def one(p, i="A-1"):
    return next(r for r in read_rows(p) if r["achievement_id"] == i)


def test_sidecar_path_follows_pending(tmp_path):
    assert sidecar_path(P(tmp_path)) == tmp_path / "pending_achievements.auto.json"


def test_first_import_writes_sidecar_sorted_utf8(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-2"), cand("A-1")], set())
    text = sidecar_path(p).read_text(encoding="utf-8")
    assert "原標題" in text and text.index('"A-1"') < text.index('"A-2"')
    assert side(p)["A-1"]["src"]["title"] == "原標題" and side(p)["A-1"]["judged"] == {}


# Focus 1
def test_user_edit_kept_untouched_fields_follow_source(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1")], set())
    rows = read_rows(p)
    rows[0]["memory"] = "我的回憶"
    rows[0]["level"] = "4"
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", item="B", domain="sports", evidence="e2", source="s:9", level="1",
                           memory="來源")], set())
    r = one(p)
    assert r["level"] == "4" and r["memory"] == "我的回憶"              # 改過的保留
    assert (r["item"], r["domain"], r["evidence"], r["source"]) == ("B", "sports", "e2", "s:9")  # 沒改的跟著來源


def test_untouched_follow_source_then_edit_after_source_change_kept(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1")], set())
    merge_pending(p, [cand("A-1", title="第二版")], set())
    assert one(p)["title"] == "第二版"
    rows = read_rows(p)
    rows[0]["title"] = "手改"
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", title="第三版")], set())
    assert one(p)["title"] == "手改"


# Focus 2
def test_judged_values_kept_and_user_level_edit_kept(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", level="")], set())
    apply_judgments(p, [{"achievement_id": "A-1", "level": 3, "suggest": "y", "reason": "因為"}], make_domains())
    merge_pending(p, [cand("A-1", level="")], set())
    r = one(p)
    assert (r["level"], r["suggest"], r["reason"]) == ("3", "y", "因為")
    rows = read_rows(p)
    rows[0]["level"] = "5"
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", level="")], set())
    assert one(p)["level"] == "5"


# Focus 3
def test_decided_rows_keep_all_old_values(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1")], set())
    rows = read_rows(p)
    rows[0].update(decision="y", evidence="舊證據", source="舊出處")
    write_rows(p, PENDING_FIELDS, rows)
    merge_pending(p, [cand("A-1", title="來源新", evidence="新證據", source="新出處", date="2030")], set())
    r = one(p)
    assert (r["decision"], r["title"], r["evidence"], r["source"], r["date"]) == ("y", "原標題", "舊證據", "舊出處", "2024-01")


def test_manual_row_without_decision_survives(tmp_path):
    p = P(tmp_path)
    write_rows(p, PENDING_FIELDS, [cand("M-1", origin="manual", title="手動補")])
    merge_pending(p, [cand("A-1")], set())
    assert {r["achievement_id"] for r in read_rows(p)} == {"M-1", "A-1"}
    merge_pending(p, [cand("A-1")], set())  # 再來一次還在
    assert one(p, "M-1")["title"] == "手動補"


def test_stale_machine_row_without_decision_dropped(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1"), cand("A-2")], set())
    merge_pending(p, [cand("A-1")], set())
    assert [r["achievement_id"] for r in read_rows(p)] == ["A-1"]
    assert "A-2" not in side(p)


# Focus 4
def test_legacy_rows_keep_old_values_and_sidecar_backfilled(tmp_path):
    p = P(tmp_path)
    write_rows(p, PENDING_FIELDS, [cand("A-1", title="舊標題", level="3", suggest="y", reason="舊理由", evidence="舊證")])
    assert not sidecar_path(p).exists()
    merge_pending(p, [cand("A-1", title="來源標題", level="", evidence="新證")], set())
    r = one(p)
    assert (r["title"], r["level"], r["suggest"], r["reason"], r["evidence"]) == ("舊標題", "3", "y", "舊理由", "舊證")
    s = side(p)["A-1"]
    assert s["src"]["title"] == "來源標題"
    assert s["judged"] == {"level": "3", "suggest": "y", "reason": "舊理由"}


def test_corrupt_sidecar_falls_back_conservative_with_warning(tmp_path, capsys):
    p = P(tmp_path)
    write_rows(p, PENDING_FIELDS, [cand("A-1", title="舊標題", suggest="n", level="2")])
    sidecar_path(p).write_text("{壞掉", encoding="utf-8")
    merge_pending(p, [cand("A-1", title="新標題")], set())
    assert one(p)["title"] == "舊標題" and one(p)["level"] == "2"
    assert "旁檔" in capsys.readouterr().err
    assert sidecar_path(p).read_text(encoding="utf-8") == "{壞掉"      # 壞檔不被覆蓋


def test_wrong_shape_sidecar_treated_as_corrupt(tmp_path, capsys):
    p = P(tmp_path)
    write_rows(p, PENDING_FIELDS, [cand("A-1", title="舊標題")])
    sidecar_path(p).write_text("[1,2]", encoding="utf-8")
    merge_pending(p, [cand("A-1", title="新標題")], set())
    assert one(p)["title"] == "舊標題" and "旁檔" in capsys.readouterr().err


# Focus 5
def test_apply_judgments_updates_sidecar_judged(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1")], set())
    apply_judgments(p, [{"achievement_id": "A-1", "level": 2, "suggest": "n", "reason": "r", "item": "B"}], make_domains())
    j = side(p)["A-1"]["judged"]
    assert (j["level"], j["suggest"], j["reason"], j["item"]) == ("2", "n", "r", "B")


def test_apply_judgments_skipped_decided_not_in_sidecar_judged(tmp_path):
    p = P(tmp_path)
    merge_pending(p, [cand("A-1")], set())
    rows = read_rows(p)
    rows[0]["decision"] = "y"
    write_rows(p, PENDING_FIELDS, rows)
    apply_judgments(p, [{"achievement_id": "A-1", "level": 2, "suggest": "n"}], make_domains())
    assert side(p)["A-1"]["judged"] == {}


def test_apply_pending_clears_accepted_from_sidecar(tmp_path):
    write_ach(tmp_path, [])
    p = P(tmp_path)
    merge_pending(p, [cand("A-1", level="2"), cand("A-2", level="1")], set())
    rows = read_rows(p)
    rows[0]["decision"] = "y"
    write_rows(p, PENDING_FIELDS, rows)
    apply_pending(tmp_path, make_domains())
    assert set(side(p)) == {"A-2"}
