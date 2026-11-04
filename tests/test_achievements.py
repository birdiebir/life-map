"""Task 1：domains.json 與 achievements.csv 讀取、驗證、不再提起規則。"""
import json

import pytest

from _ach import ach, make_domains, real_domains, row, write_ach
from lifemap.achievements import is_suppressed, load_achievements, load_domains, load_suppress_rules
from lifemap.data import DataError


def test_real_domains_config_has_six_domains():
    d = real_domains()
    assert set(d.by_id) == {"sports", "learning", "adventure", "social", "family", "career"}
    assert d.top_n == 5 and d.visited_min_level == 1
    assert d.by_id["learning"].scores[3] == 3
    assert d.by_id["adventure"].recommend is False
    assert d.by_id["learning"].sets[0].items


def test_domains_bad_config_rejected():
    with pytest.raises(DataError):
        load_domains({"domains": {"x": {"name": "x", "levels": {}, "scores": {"0": 0}}}})  # 分數表缺 1～5


def test_loads_excel_bom_crlf(tmp_path):
    p = write_ach(tmp_path, [row(title="IELTS 6.0")], encoding="utf-8-sig", newline="\r\n")
    out = load_achievements(p, make_domains())
    assert len(out) == 1 and out[0].title == "IELTS 6.0" and out[0].level == 1 and out[0].confirmed is True


def test_blank_privacy_uses_domain_default(tmp_path):
    p = write_ach(tmp_path, [row("1", domain="learning"), row("2", domain="sports")])
    a, b = load_achievements(p, make_domains())
    assert a.privacy == "kb" and b.privacy == "local"


def test_all_errors_listed_with_row_numbers(tmp_path):
    p = write_ach(tmp_path, [
        row("1", domain="nope"),                 # 第 2 列：領域不存在
        row("2", level="9"),                     # 第 3 列：等級超出
        row("3", date="2024/01/01"),             # 第 4 列：日期格式
        row("2", title="dup"),                   # 第 5 列：ID 重複
        row("5", together="maybe"),              # 第 6 列：布林亂填
        row("6", privacy="secret"),              # 第 7 列：隱私等級不存在
        row("7", level="x"),                     # 第 8 列：等級不是整數
        row("8", item=""),                       # 第 9 列：項目必填
    ])
    with pytest.raises(DataError) as e:
        load_achievements(p, make_domains())
    msg = str(e.value)
    assert "有 8 列要修正" in msg
    for n in range(2, 10):
        assert f"第 {n} 列" in msg
    assert "領域不存在" in msg and "0～5" in msg and "重複" in msg and "隱私等級" in msg


def test_missing_column_reported(tmp_path):
    p = tmp_path / "achievements.csv"
    p.write_text("achievement_id,domain\n1,learning\n", encoding="utf-8")
    with pytest.raises(DataError, match="缺少欄位"):
        load_achievements(p, make_domains())


def test_unconfirmed_loaded_but_flagged(tmp_path):
    p = write_ach(tmp_path, [row("1", confirmed="false")])
    assert load_achievements(p, make_domains())[0].confirmed is False


def test_suppress_rules_missing_file_is_empty(tmp_path):
    assert load_suppress_rules(tmp_path / "none.json") == []


def test_suppress_single_field():
    assert is_suppressed(ach(suppressed=True), [])
    assert not is_suppressed(ach(), [])


def test_suppress_rule_domain_item_and_dates(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([
        {"domain": "learning", "item": "A", "date_from": "2020-01", "date_to": "2020-12"},
        {"domain": "sports"},
    ]), encoding="utf-8")
    rules = load_suppress_rules(p)
    assert is_suppressed(ach(domain="learning", item="A", date="2020-06"), rules)
    assert is_suppressed(ach(domain="learning", item="A", date="2020"), rules)       # 年份重疊
    assert not is_suppressed(ach(domain="learning", item="A", date="2021-01"), rules)
    assert not is_suppressed(ach(domain="learning", item="B", date="2020-06"), rules)
    assert not is_suppressed(ach(domain="learning", item="A", date=""), rules)       # 無日期不符合日期條件
    assert is_suppressed(ach(domain="sports", item="Z", date="1999"), rules)         # 只給領域＝整個領域


def test_suppress_rules_bad_format_rejected(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([{"domain": "sports", "date_from": "yesterday"}]), encoding="utf-8")
    with pytest.raises(DataError):
        load_suppress_rules(p)
