r"""M1b：候選去雜訊與項目對應規則（config\ach_rules.json＋private\achievement_rules.json）。"""
from __future__ import annotations

import json

from lifemap.ach_rules import apply_rules, load_rules


def cand(title, origin="kb_note", source="n/x.md:1", item="學習", evidence="", domain="learning"):
    return {"achievement_id": "A-" + title, "domain": domain, "item": item, "title": title, "origin": origin,
            "source": source, "evidence": evidence, "level": "", "date": "2020"}


RULES = {
    "noise": {
        "apply_to_origins": ["kb_note"],
        "min_title_chars": 6,
        "drop_title_patterns": [r"^來源[:：]", r"^[～~]", r"^[A-Za-z]:\\"],
        "require_signal": True,
        "signals": ["畢業", "獲頒", "Award", "錄取"],
    },
    "item_rules": [
        {"pattern": "碩士|Master", "item": "碩士", "domains": ["learning"]},
        {"pattern": "^高中", "item": "高中", "field": "file"},
        {"pattern": "得獎", "item": "得獎", "domain": "career", "field": "title"},
    ],
}


def test_pattern_drop_and_counts():
    rows = [cand("來源：D:\\x 畢業"), cand("～13 畢業證書"), cand("碩士畢業典禮")]
    kept, dropped = apply_rules(rows, RULES)
    assert [r["title"] for r in kept] == ["碩士畢業典禮"]
    assert sum(dropped.values()) == 2


def test_no_signal_dropped_signal_kept_in_evidence():
    rows = [cand("課程作業第三題報告內容", evidence="no"), cand("某個很長的標題在這裡", evidence="獲頒獎學金")]
    kept, dropped = apply_rules(rows, RULES)
    assert [r["title"] for r in kept] == ["某個很長的標題在這裡"]
    assert sum(dropped.values()) == 1


def test_short_title_dropped_unless_signal():
    rows = [cand("S2"), cand("之後"), cand("碩士畢業", evidence="")]
    kept, _ = apply_rules(rows, RULES)
    assert [r["title"] for r in kept] == ["碩士畢業"]


def test_noise_only_for_listed_origins():
    rows = [cand("S2", origin="csv"), cand("來源：x", origin="csv")]
    kept, dropped = apply_rules(rows, RULES)
    assert len(kept) == 2 and dropped == {}


def test_item_rules_first_hit_and_fields():
    rows = [cand("Master of Science 畢業", source="n/其他.md:3"),
            cand("學士畢業典禮", source="高中_成績.md:3"),
            cand("獲得得獎肯定畢業", source="n/a.md:1")]
    kept, _ = apply_rules(rows, RULES)
    assert kept[0]["item"] == "碩士"
    assert kept[1]["item"] == "高中"          # field=file 比對檔名
    assert kept[2]["item"] == "得獎" and kept[2]["domain"] == "career"


def test_item_rules_no_hit_keeps_default():
    kept, _ = apply_rules([cand("普通畢業事件記錄")], RULES)
    assert kept[0]["item"] == "學習"


def test_item_rules_apply_to_all_origins_within_their_domains():
    kept, _ = apply_rules([cand("Master 入職", origin="csv", item="學習")], RULES)
    assert kept[0]["item"] == "碩士"  # 來源不限，只看領域


def test_item_rule_with_domains_skips_other_domains():
    kept, _ = apply_rules([cand("Master of Science 畢業", origin="csv", item="職涯", domain="career")], RULES)
    assert kept[0]["item"] == "職涯"  # 職涯表的候選不被學習規則改掉
    # 沒寫 domains 的規則套用到全部領域
    kept, _ = apply_rules([cand("獲得得獎肯定", origin="csv", item="職涯", domain="travel")], RULES)
    assert kept[0]["item"] == "得獎"


def test_load_rules_private_lists_first_scalars_override(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(RULES), encoding="utf-8")
    priv = tmp_path / "p.json"
    priv.write_text(json.dumps({"noise": {"min_title_chars": 2, "signals": ["證照甲"],
                                          "drop_title_patterns": ["^私人雜訊"]},
                                "item_rules": [{"pattern": "畢業", "item": "私人"}]}), encoding="utf-8")
    r = load_rules(cfg, priv)
    assert r["noise"]["min_title_chars"] == 2
    assert r["noise"]["drop_title_patterns"][0] == "^私人雜訊" and len(r["noise"]["drop_title_patterns"]) == 4
    assert r["noise"]["signals"][0] == "證照甲" and "畢業" in r["noise"]["signals"]
    assert r["noise"]["require_signal"] is True
    assert r["item_rules"][0]["item"] == "私人" and len(r["item_rules"]) == 4
    # private 優先命中
    kept, _ = apply_rules([cand("碩士畢業典禮")], r)
    assert kept[0]["item"] == "私人"


def test_load_rules_without_private(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(RULES), encoding="utf-8")
    assert load_rules(cfg, tmp_path / "nope.json") == load_rules(cfg)


def test_real_config_loads_and_filters():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    r = load_rules(root / "config" / "ach_rules.json")
    rows = [cand("來源：C:\\假目錄\\x"), cand("C:\\假目錄\\y 畢業"), cand("～13 畢業證書"), cand("學士學位畢業"),
            cand("獲頒獎學金 Scholarship"), cand("Master of Science 畢業", domain="career")]
    kept, _ = apply_rules(rows, r)
    assert [x["title"] for x in kept] == ["學士學位畢業", "獲頒獎學金 Scholarship", "Master of Science 畢業"]
    assert kept[0]["item"] == "學士"
    assert kept[2]["item"] == "學習"  # 學習類規則只套用到 learning 領域


def test_real_config_has_no_personal_rules():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "config" / "ach_rules.json").read_text(encoding="utf-8")
    for s in ("閱讀涵蓋率", "未能讀取", "原文含", "低優先", "AU\\\\$", "Application ref"):
        assert s not in text


def test_shipped_award_rule_does_not_touch_family_candidates():
    from pathlib import Path
    rules = load_rules(Path(__file__).resolve().parent.parent / "config" / "ach_rules.json",
                       Path(__file__).resolve().parent.parent / "private.example" / "achievement_rules.json")
    fam, _ = apply_rules([cand("全家得獎慶祝", origin="kb_table", item="家人大事", domain="family")], rules)
    assert fam[0]["item"] == "家人大事"
    car, _ = apply_rules([cand("專案得獎", origin="csv", item="職涯", domain="career")], rules)
    assert car[0]["item"] == "得獎"
