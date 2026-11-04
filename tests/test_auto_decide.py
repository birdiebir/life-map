r"""預設照 Opus 建議：把握度欄 certainty、auto_decide、apply_judgments.py --auto-decide。"""
import json
import subprocess
import sys

import pytest

from _ach import ROOT, real_domains
from lifemap.ach_pending import PENDING_FIELDS, apply_judgments, apply_pending, auto_decide, is_auto, merge_pending
from lifemap.data import DataError
from lifemap.pending import read_rows, write_rows


def cand(i, **kw):
    r = {f: "" for f in PENDING_FIELDS}
    r.update(achievement_id=i, domain="learning", item="A", title=f"T{i}", date="2024-01", origin="csv",
             confirmed="false", together="false", suppressed="false", level="2", evidence="e")
    r.update(kw)
    return r


def pend(tmp_path, rows):
    p = tmp_path / "pending_achievements.csv"
    write_rows(p, PENDING_FIELDS, rows)
    return p


def by(p):
    return {r["achievement_id"]: r for r in read_rows(p)}


def test_fields_include_certainty_and_auto():
    assert "certainty" in PENDING_FIELDS and "auto" in PENDING_FIELDS


def test_auto_decide_rules(tmp_path):
    p = pend(tmp_path, [cand("A-1", suggest="y", certainty="高"), cand("A-2", suggest="n", certainty="高"),
                        cand("A-3", suggest="y", certainty="低"), cand("A-4", suggest="y"),
                        cand("A-5"), cand("A-6", suggest="y", certainty="高", decision="n")])
    res = auto_decide(p)
    assert res == {"auto_y": 1, "auto_n": 1, "ask_user": 2, "no_suggest": 1, "suspected_dup": 0}
    b = by(p)
    assert (b["A-1"]["decision"], b["A-1"]["auto"]) == ("y", "y")
    assert (b["A-2"]["decision"], b["A-2"]["auto"]) == ("n", "n")
    assert b["A-3"]["decision"] == "" and b["A-4"]["decision"] == "" and b["A-5"]["decision"] == ""
    assert (b["A-6"]["decision"], b["A-6"]["auto"]) == ("n", "")       # 使用者已決定的不碰


def test_default_certainty_applies_to_blank_only(tmp_path):
    p = pend(tmp_path, [cand("A-1", suggest="y"), cand("A-2", suggest="n", certainty="低"), cand("A-3")])
    res = auto_decide(p, "高")
    assert res["auto_y"] == 1 and res["ask_user"] == 1 and res["no_suggest"] == 1
    b = by(p)
    assert b["A-1"]["certainty"] == "高" and b["A-1"]["decision"] == "y"
    assert b["A-2"]["certainty"] == "低" and b["A-2"]["decision"] == ""
    with pytest.raises(DataError):
        auto_decide(p, "中")


def test_user_override_wins_and_is_not_auto(tmp_path):
    p = pend(tmp_path, [cand("A-1", suggest="y", certainty="高")])
    auto_decide(p)
    assert is_auto(by(p)["A-1"])
    rows = read_rows(p)
    rows[0]["decision"] = "n"                                  # 使用者在 Excel 改成 n
    write_rows(p, PENDING_FIELDS, rows)
    assert not is_auto(by(p)["A-1"])
    auto_decide(p)                                             # 再跑一次不會改回去
    assert by(p)["A-1"]["decision"] == "n"
    # 重匯入保留使用者的決定與 auto 欄
    merge_pending(p, [cand("A-1")], set())
    assert by(p)["A-1"]["decision"] == "n"


def test_auto_n_stays_in_pending_and_not_resurfaced_auto_y_applies(tmp_path):
    d = real_domains()
    p = pend(tmp_path, [cand("A-1", suggest="y", certainty="高", domain="learning", level="2"),
                        cand("A-2", suggest="n", certainty="高")])
    (tmp_path / "achievements.csv").write_text("achievement_id,domain,item,title,level,date,together,memory,photo,source,origin,confidence,confirmed,privacy,suppressed\n", encoding="utf-8")
    auto_decide(p)
    res = apply_pending(tmp_path, d)
    assert res["accepted"] == 1
    rest = by(p)
    assert list(rest) == ["A-2"] and rest["A-2"]["decision"] == "n"
    merge_pending(p, [cand("A-2", suggest="")], {"A-1"})        # 重匯入：n 的留著
    assert by(p)["A-2"]["decision"] == "n"


def test_apply_judgments_writes_certainty_and_validates(tmp_path):
    d = real_domains()
    p = pend(tmp_path, [cand("A-1"), cand("A-2")])
    apply_judgments(p, [{"achievement_id": "A-1", "level": 3, "suggest": "y", "reason": "r", "certainty": "高"},
                        {"achievement_id": "A-2", "level": 1, "suggest": "n", "reason": "r"}], d)
    b = by(p)
    assert b["A-1"]["certainty"] == "高" and b["A-2"]["certainty"] == ""
    with pytest.raises(DataError, match="certainty"):
        apply_judgments(p, [{"achievement_id": "A-2", "level": 1, "suggest": "n", "certainty": "中"}], d)
    assert by(p)["A-2"]["certainty"] == ""


def test_reimport_keeps_certainty_on_undecided_row(tmp_path):
    p = pend(tmp_path, [cand("A-1", suggest="y", certainty="低", reason="r")])
    merge_pending(p, [cand("A-1")], set())
    assert by(p)["A-1"]["certainty"] == "低"


def _run(*args):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "apply_judgments.py"), *args],
                          capture_output=True, text=True, encoding="utf-8")


def test_script_auto_decide_dry_run_then_write(tmp_path):
    p = pend(tmp_path, [cand("A-1", suggest="y", certainty="高"), cand("A-2", suggest="y")])
    r = _run("--auto-decide", "--data-dir", str(tmp_path))
    assert r.returncode == 0 and "收 1" in r.stdout and "低把握度（要問使用者）1" in r.stdout and "試跑" in r.stdout
    assert by(p)["A-1"]["decision"] == ""                       # 試跑沒寫
    r = _run("--auto-decide", "--write", "--data-dir", str(tmp_path))
    assert r.returncode == 0 and by(p)["A-1"]["decision"] == "y"
    assert list(tmp_path.glob("pending_achievements.before_auto.*.csv"))


def test_script_with_judgments_and_auto(tmp_path):
    p = pend(tmp_path, [cand("A-1"), cand("A-2")])
    j = tmp_path / "j.json"
    j.write_text(json.dumps([{"achievement_id": "A-1", "level": 3, "suggest": "n", "certainty": "高", "reason": "x"},
                             {"achievement_id": "A-2", "level": 2, "suggest": "y", "certainty": "低", "reason": "y"}]),
                 encoding="utf-8")
    r = _run(str(j), "--auto-decide", "--write", "--data-dir", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    b = by(p)
    assert b["A-1"]["decision"] == "n" and b["A-2"]["decision"] == "" and b["A-2"]["certainty"] == "低"


def test_script_needs_judgments_or_auto(tmp_path):
    pend(tmp_path, [cand("A-1")])
    assert _run("--data-dir", str(tmp_path)).returncode != 0


def test_script_bad_certainty_leaves_file_untouched(tmp_path):
    p = pend(tmp_path, [cand("A-1")])
    j = tmp_path / "j.json"
    j.write_text(json.dumps([{"achievement_id": "A-1", "level": 3, "suggest": "y", "certainty": "中"}]), encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    r = _run(str(j), "--auto-decide", "--write", "--data-dir", str(tmp_path))
    assert r.returncode == 1 and p.read_text(encoding="utf-8") == before


def test_user_cleared_auto_decision_is_not_refilled(tmp_path):
    """使用者把自動填的 decision 清空＝撤回；再跑 auto_decide 不能填回去。"""
    p = pend(tmp_path, [cand("A-1", suggest="y", certainty="高")])
    assert auto_decide(p)["auto_y"] == 1
    rows = read_rows(p)
    rows[0]["decision"] = ""                      # 使用者在 Excel 清空，auto 欄還留著 y
    write_rows(p, PENDING_FIELDS, rows)
    res = auto_decide(p)
    assert res["auto_y"] == 0 and res["ask_user"] == 1
    assert by(p)["A-1"]["decision"] == ""


def write_main(tmp_path, rows):
    from lifemap.achievements import ACH_FIELDS
    write_rows(tmp_path / "achievements.csv", ACH_FIELDS, rows)


def main_row(i, title, domain="learning", source="教育/a.md:10"):
    from lifemap.achievements import ACH_FIELDS
    r = {f: "" for f in ACH_FIELDS}
    r.update(achievement_id=i, domain=domain, item="A", title=title, level="3", date="2019-07", source=source,
             origin="kb_note", confirmed="true", together="false", suppressed="false")
    return r


def test_suspected_duplicate_of_main_file_not_auto_decided(tmp_path):
    """KB 一改 ID 就換：同領域、標題正規化後相同，或同來源檔且標題相似的新候選，不自動決定、把握度強制低、reason 註明舊 ID。"""
    write_main(tmp_path, [main_row("A-old1", "XYZ-2 範例救護證照"), main_row("A-old2", "範例大學 ABC 社區領導獎")])
    p = pend(tmp_path, [
        cand("A-n1", title="XYZ-2  範例救護證照！", suggest="y", certainty="高"),                    # 正規化後相同
        cand("A-n2", title="範例大學ABC社區領導獎（2022）", suggest="y", certainty="高", source="教育/a.md:99"),  # 同檔、相似
        cand("A-n3", title="完全不同的新成就", suggest="y", certainty="高", source="教育/b.md:3"),
        cand("A-n4", title="XYZ-2 範例救護證照", domain="career", suggest="y", certainty="高"),       # 不同領域不算
    ])
    res = auto_decide(p)
    b = by(p)
    assert res["suspected_dup"] == 2 and res["auto_y"] == 2
    for i, old in (("A-n1", "A-old1"), ("A-n2", "A-old2")):
        assert b[i]["decision"] == "" and b[i]["certainty"] == "低" and f"疑似重複：{old}" in b[i]["reason"]
    assert b["A-n3"]["decision"] == "y" and b["A-n4"]["decision"] == "y"


def test_suspected_duplicate_of_decided_pending_row(tmp_path):
    p = pend(tmp_path, [cand("A-old", title="MIT conditional offer", decision="y"),
                        cand("A-new", title="MIT Conditional Offer", suggest="y", certainty="高")])
    res = auto_decide(p)
    b = by(p)
    assert res["suspected_dup"] == 1 and b["A-new"]["decision"] == "" and "疑似重複：A-old" in b["A-new"]["reason"]
    assert auto_decide(p)["suspected_dup"] == 1 and by(p)["A-new"]["reason"].count("疑似重複") == 1     # 重跑不重複加註


def test_script_prints_suspected_dup_count(tmp_path):
    """apply_judgments.py --auto-decide 的輸出要印出疑似重複的筆數。"""
    p = pend(tmp_path, [cand("A-old", title="MIT conditional offer", decision="y"),
                        cand("A-new", title="MIT Conditional Offer", suggest="y", certainty="高")])
    r = _run("--auto-decide", "--data-dir", str(tmp_path))
    assert r.returncode == 0 and "（其中疑似重複 1）" in r.stdout
    assert by(p)["A-new"]["decision"] == ""                      # 試跑不寫
