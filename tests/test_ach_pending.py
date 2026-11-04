"""Task 4：pending_achievements.csv 合併與收進 achievements.csv。"""
import pytest

from _ach import make_domains, row, write_ach
from lifemap.ach_pending import PENDING_FIELDS, apply_pending, merge_pending
from lifemap.achievements import ACH_FIELDS, load_achievements
from lifemap.data import DataError
from lifemap.pending import read_rows, write_rows


def cand(i, title="候選", **kw):
    r = {f: "" for f in PENDING_FIELDS}
    r.update(achievement_id=i, domain="learning", item="A", title=title, date="2024-01", origin="csv",
             confirmed="false", together="false", suppressed="false", evidence="e")
    r.update(kw)
    return r


def test_first_merge_writes_candidates(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    merge_pending(p, [cand("A-1"), cand("A-2")], set())
    assert [r["achievement_id"] for r in read_rows(p)] == ["A-1", "A-2"]


def test_decisions_and_edits_kept_on_reimport(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    write_rows(p, PENDING_FIELDS, [cand("A-1", decision="y", level="4", memory="我寫的回憶")])
    merge_pending(p, [cand("A-1")], set())
    r = read_rows(p)[0]
    assert (r["decision"], r["level"], r["memory"]) == ("y", "4", "我寫的回憶")


def test_rejected_stay_even_if_not_regenerated(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    write_rows(p, PENDING_FIELDS, [cand("A-1", decision="n"), cand("A-9", decision="")])
    merge_pending(p, [cand("A-2")], set())
    ids = [r["achievement_id"] for r in read_rows(p)]
    assert "A-1" in ids and "A-2" in ids and "A-9" not in ids


def test_already_in_achievements_skipped(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    write_rows(p, PENDING_FIELDS, [cand("A-1", decision="y")])
    merge_pending(p, [cand("A-1"), cand("A-2")], {"A-1"})
    assert [r["achievement_id"] for r in read_rows(p)] == ["A-2"]


def test_apply_moves_yes_to_achievements_confirmed(tmp_path):
    d = make_domains()
    write_ach(tmp_path, [row("1", title="既有")])
    write_rows(tmp_path / "pending_achievements.csv", PENDING_FIELDS, [
        cand("A-1", title="收", decision="y", level="3", together="true", memory="好"),
        cand("A-2", title="不收", decision="n"),
        cand("A-3", title="還沒決定"),
    ])
    r = apply_pending(tmp_path, d)
    assert r == {"accepted": 1, "kept": 2}
    achs = load_achievements(tmp_path / "achievements.csv", d)
    new = [a for a in achs if a.achievement_id == "A-1"][0]
    assert new.confirmed and new.level == 3 and new.together and new.memory == "好"
    assert len(achs) == 2
    assert {r["achievement_id"] for r in read_rows(tmp_path / "pending_achievements.csv")} == {"A-2", "A-3"}


def test_apply_creates_achievements_file_when_missing(tmp_path):
    write_rows(tmp_path / "pending_achievements.csv", PENDING_FIELDS, [cand("A-1", decision="y", level="2")])
    apply_pending(tmp_path, make_domains())
    assert (tmp_path / "achievements.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_rows(tmp_path / "achievements.csv")[0]["achievement_id"] == "A-1"
    assert list(read_rows(tmp_path / "achievements.csv")[0]) == ACH_FIELDS


def test_apply_rejects_bad_decision(tmp_path):
    write_rows(tmp_path / "pending_achievements.csv", PENDING_FIELDS, [cand("A-1", decision="maybe")])
    with pytest.raises(DataError, match="decision"):
        apply_pending(tmp_path, make_domains())


def test_apply_blank_level_fails_without_touching_files(tmp_path):
    write_ach(tmp_path, [row("1")])
    before = (tmp_path / "achievements.csv").read_bytes()
    write_rows(tmp_path / "pending_achievements.csv", PENDING_FIELDS, [cand("A-1", decision="y", level="")])
    with pytest.raises(DataError):
        apply_pending(tmp_path, make_domains())
    assert (tmp_path / "achievements.csv").read_bytes() == before
    assert len(read_rows(tmp_path / "pending_achievements.csv")) == 1


def test_apply_nothing_when_no_yes(tmp_path):
    write_rows(tmp_path / "pending_achievements.csv", PENDING_FIELDS, [cand("A-1")])
    assert apply_pending(tmp_path, make_domains()) == {"accepted": 0, "kept": 1}


def test_yes_rows_kept_even_if_not_regenerated(tmp_path):
    p = tmp_path / "pending_achievements.csv"
    write_rows(p, PENDING_FIELDS, [cand("A-1", decision="y", level="3")])
    merge_pending(p, [cand("A-2")], set())
    kept = {r["achievement_id"]: r for r in read_rows(p)}
    assert kept["A-1"]["decision"] == "y" and kept["A-1"]["level"] == "3"
