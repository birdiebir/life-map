r"""M2-a：TrainingLogSource（訓練紀錄表 → 每個運動項目一筆候選）。全部用假資料。"""
import json

import pytest

from lifemap.ach_sources import TrainingLogSource, build_sources
from lifemap.achievements import ACH_FIELDS

NOTE = """# 假的訓練筆記

## 本週表（每週）
| 日期 | 類別 | 內容 |
|---|---|---|
| 01/05 | 羽球 | 單打練習 |
| 01/06 | 胸肩重訓 | 動作甲 100kg |
| 01/07 | 羽球 | 雙打 |
| 01/08 | 休息 | — |
| 01/12(一) | 羽球 | 單打 |

## 下一段
| 日期 | 類別 | 內容 |
|---|---|---|
| 04/20 | 羽球 | 單打 |
| 04/22 | 徒手 | 伏地挺身 |

## 更早的訓練紀錄
| 日期 | 類別 | 內容 |
|---|---|---|
| 2025-03-02 | 徒手 | 引體向上 |

## 別的表（不是訓練）
| 品項 | 價格 |
|---|---|
| 蛋白粉 | 100 |
"""

CFG = {
    "type": "training_log", "name": "假訓練", "domain": "sports", "week_start": "2026-01-05",
    "date_col": "日期", "category_col": "類別",
    "item_map": {"羽球": "羽球", "胸肩": "重訓", "徒手": "徒手訓練"},
}


def _src(tmp_path, text=NOTE, **over):
    p = tmp_path / "log.md"
    p.write_text(text, encoding="utf-8")
    cfg = {**CFG, "files": [str(p)], "root": str(tmp_path), **over}
    return TrainingLogSource(cfg)


def _by_item(cands):
    return {c["item"]: c for c in cands}


def test_one_candidate_per_item_and_unmapped_ignored(tmp_path):
    cands = _src(tmp_path).candidates()
    assert sorted(c["item"] for c in cands) == ["徒手訓練", "羽球", "重訓"]      # 「休息」沒對應、蛋白粉表沒有日期欄
    c = cands[0]
    assert set(ACH_FIELDS) <= set(c) and "evidence" in c
    assert c["domain"] == "sports" and c["origin"] == "training_log" and c["confirmed"] == "false"
    assert c["source"] == f"log.md#{c['item']}"


def test_yearless_dates_get_year_from_week_start(tmp_path):
    by = _by_item(_src(tmp_path).candidates())
    assert by["羽球"]["date"] == "2026-01-05"             # 候選日期＝第一次
    assert "2026-04-20" in by["羽球"]["evidence"]        # 最後一次，補了年份
    assert by["徒手訓練"]["date"] == "2025-03-02"         # 有完整日期的照用


def test_dates_before_week_start_roll_to_next_year(tmp_path):
    note = "| 日期 | 類別 |\n|---|---|\n| 12/28 | 羽球 |\n| 01/10 | 羽球 |\n"
    ev = _src(tmp_path, note, week_start="2026-12-14").candidates()[0]["evidence"]
    assert "2026-12-28" in ev and "2027-01-10" in ev            # 跨年：起始日之前很多天的月日算隔年
    # 起始日前幾天（同一週補記）仍算同一年，不被推到隔年
    near = "| 日期 | 類別 |\n|---|---|\n| 01/03 | 羽球 |\n| 01/05 | 羽球 |\n"
    assert _src(tmp_path, near).candidates()[0]["date"] == "2026-01-03"


def test_no_week_start_skips_yearless_rows_and_reports(tmp_path):
    p = tmp_path / "log.md"
    p.write_text(NOTE, encoding="utf-8")
    cfg = {k: v for k, v in CFG.items() if k != "week_start"}
    src = TrainingLogSource({**cfg, "files": [str(p)], "root": str(tmp_path)})
    cands = src.candidates()
    assert [c["item"] for c in cands] == ["徒手訓練"]      # 只剩有完整日期的那一列
    assert src.skipped["無年份"] == 6


def test_level_by_span_and_coverage(tmp_path):
    rows = "".join(f"| 2026-{m:02d}-{d:02d} | 羽球 |\n" for m, d in [(1, 5), (1, 12), (1, 19), (1, 26)])
    # 4 週內：連續但不到 3 個月 → 偏保守 2
    low = _src(tmp_path, "| 日期 | 類別 |\n|---|---|\n" + rows).candidates()[0]
    assert low["level"] == "2"
    # 只有 2 週紀錄 → 1
    two = _src(tmp_path, "| 日期 | 類別 |\n|---|---|\n| 2026-01-05 | 羽球 |\n| 2026-01-12 | 羽球 |\n").candidates()[0]
    assert two["level"] == "1"
    # 4 個月、每週都有 → 3
    from datetime import date, timedelta
    d0 = date(2026, 1, 5)
    weekly = "".join(f"| {(d0 + timedelta(weeks=i)).isoformat()} | 羽球 |\n" for i in range(18))
    assert _src(tmp_path, "| 日期 | 類別 |\n|---|---|\n" + weekly).candidates()[0]["level"] == "3"
    # 14 個月、每週都有 → 5
    year = "".join(f"| {(d0 + timedelta(weeks=i)).isoformat()} | 羽球 |\n" for i in range(60))
    assert _src(tmp_path, "| 日期 | 類別 |\n|---|---|\n" + year).candidates()[0]["level"] == "5"
    # 14 個月但只有頭尾兩週：被「有紀錄不到 3 週」擋下 → 1（涵蓋率那條另有測試）
    sparse = "| 日期 | 類別 |\n|---|---|\n| 2025-01-06 | 羽球 |\n| 2026-03-30 | 羽球 |\n"
    assert _src(tmp_path, sparse).candidates()[0]["level"] == "1"


def test_evidence_has_period_and_weeks_but_no_content(tmp_path):
    by = _by_item(_src(tmp_path).candidates())
    ev = by["重訓"]["evidence"]
    assert "2026-01-06" in ev and "1 週" in ev
    for c in by.values():
        blob = json.dumps(c, ensure_ascii=False)
        assert "100kg" not in blob and "動作甲" not in blob and "伏地挺身" not in blob and "引體向上" not in blob


def test_ids_stable_and_title_does_not_depend_on_last_date(tmp_path):
    a = _by_item(_src(tmp_path).candidates())["羽球"]
    longer = NOTE.replace("| 04/22 | 徒手 | 伏地挺身 |", "| 04/22 | 徒手 | 伏地挺身 |\n| 04/27 | 羽球 | 單打 |")
    b = _by_item(_src(tmp_path, longer).candidates())["羽球"]
    assert a["achievement_id"] == b["achievement_id"] and a["title"] == b["title"]
    assert a["evidence"] != b["evidence"]


def test_bom_crlf_and_header_variants(tmp_path):
    p = tmp_path / "log.md"
    p.write_bytes(("| 日期 | 類別 |\r\n|---|---|\r\n| 2026-02-02 | 羽球 |\r\n").encode("utf-8-sig"))
    src = TrainingLogSource({**CFG, "files": [str(p)]})
    assert [c["item"] for c in src.candidates()] == ["羽球"]


def test_missing_required_config_raises_clear_error(tmp_path):
    with pytest.raises(KeyError):
        TrainingLogSource({"type": "training_log", "domain": "sports", "files": []}).candidates()


def test_build_sources_resolves_relative_and_registers_type(tmp_path):
    (tmp_path / "log.md").write_text(NOTE, encoding="utf-8")
    cfg = {"sources": [{**CFG, "files": ["log.md"]}]}
    [s] = build_sources(cfg, base_dir=tmp_path)
    assert isinstance(s, TrainingLogSource) and len(s.candidates()) == 3


def test_glob_and_exclude(tmp_path):
    (tmp_path / "a.md").write_text(NOTE, encoding="utf-8")
    (tmp_path / "skip.md").write_text(NOTE, encoding="utf-8")
    src = TrainingLogSource({**CFG, "glob": str(tmp_path / "*.md"), "exclude": ["skip.md"]})
    assert len(src.candidates()) == 3

