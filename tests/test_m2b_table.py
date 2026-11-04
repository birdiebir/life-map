r"""M2-b：MarkdownTableSource（家人領域：時間軸表、送禮紀錄表 → 候選）。全部用假資料。"""
import pytest

from lifemap.ach_sources import MarkdownTableSource, build_sources
from lifemap.achievements import ACH_FIELDS

TIMELINE = """# 假的家族時間軸

### 2019

| 日期 | 事件 | 相關人物 | 類型 |
|---|---|---|---|
| 2019-03-02 | 全家去甲地過年旅行 | 爸、媽 | 家族大事 |
| 2019-04-10~2019-04-12 | 幫忙處理搬家 | 爸 | 家族大事/財務 |
| 2019-05-01 | 買了一台家電 | 媽 | 財務 |
| 2019-06-06 | 爸爸生日聚餐 | 爸、媽 | 生日 |
| 待定 | 沒有日期的事 | 爸 | 家族大事 |

### 2020

| 日期 | 事件 | 相關人物 | 類型 |
|---|---|---|---|
| 2020-02-02 | 一個非常長的事件描述，用來測試標題會被截斷在六十個字以內所以這裡刻意寫得很長很長很長很長很長很長很長很長很長很長很長很長很長很長 | 爸 | 家族大事 |

## 別的表

| 品項 | 價格 |
|---|---|
| 蛋白粉 | 100 |
"""

CFG = {"type": "md_table", "name": "假時間軸", "domain": "family", "item": "家人大事",
       "date_col": "日期", "title_cols": ["事件"],
       "filter": {"類型": ["家族大事", "生日"]}, "exclude": {"類型": ["財務"]},
       "item_col": "類型", "item_map": {"生日": "生日送禮", "家族大事": "家人大事"}}


def _src(tmp_path, text=TIMELINE, **over):
    p = tmp_path / "t.md"
    p.write_text(text, encoding="utf-8")
    return MarkdownTableSource({**CFG, "files": [str(p)], "root": str(tmp_path), **over})


def test_filter_exclude_and_undated_rows(tmp_path):
    cands = _src(tmp_path).candidates()
    assert [c["title"][:7] for c in cands] == ["全家去甲地過年", "爸爸生日聚餐", "一個非常長的事"]
    # 「家族大事/財務」被 exclude 擋掉；「財務」不在 filter；沒日期的列略過；別的表沒有日期欄
    c = cands[0]
    assert set(ACH_FIELDS) <= set(c) and c["evidence"]
    assert c["domain"] == "family" and c["origin"] == "kb_table" and c["confirmed"] == "false"
    assert c["date"] == "2019-03-02" and c["source"] == "t.md:7"


def test_item_map_first_match_and_default(tmp_path):
    by = {c["title"][:4]: c["item"] for c in _src(tmp_path).candidates()}
    assert by["全家去甲"] == "家人大事" and by["爸爸生日"] == "生日送禮"
    no_map = {c["item"] for c in _src(tmp_path, item_col=None, item_map=None).candidates()}
    assert no_map == {"家人大事"}


def test_range_date_uses_first_and_title_truncated(tmp_path):
    cands = _src(tmp_path, exclude={}).candidates()
    moving = next(c for c in cands if "搬家" in c["title"])
    assert moving["date"] == "2019-04-10"
    long = cands[-1]
    assert len(long["title"]) == 60


def test_multiple_title_cols_and_year_only_date(tmp_path):
    gift = "| 年份 | 對象 | 場合 | 送了什麼 |\n|---|---|---|---|\n| 2026 | 甲 | 生日 | 禮物乙 |\n| — | — | — | （送出後補一列） |\n"
    cands = _src(tmp_path, gift, date_col="年份", title_cols=["場合", "對象", "送了什麼"], filter={}, exclude={},
                 item_col=None, item_map=None, item="生日送禮").candidates()
    assert len(cands) == 1
    assert cands[0]["title"] == "生日｜甲｜禮物乙" and cands[0]["date"] == "2026"


def test_ids_stable_and_line_shift_does_not_change_id(tmp_path):
    a = [c["achievement_id"] for c in _src(tmp_path).candidates()]
    b = [c["achievement_id"] for c in _src(tmp_path, "插入一行\n" + TIMELINE).candidates()]
    assert a == b and len(set(a)) == 3


def test_bom_crlf(tmp_path):
    p = tmp_path / "t.md"
    p.write_bytes(TIMELINE.replace("\n", "\r\n").encode("utf-8-sig"))
    assert len(MarkdownTableSource({**CFG, "files": [str(p)]}).candidates()) == 3


def test_required_config_missing_raises(tmp_path):
    with pytest.raises(KeyError):
        MarkdownTableSource({"type": "md_table", "domain": "family", "files": []}).candidates()


def test_build_sources_and_glob_exclude(tmp_path):
    (tmp_path / "a.md").write_text(TIMELINE, encoding="utf-8")
    (tmp_path / "skip.md").write_text(TIMELINE, encoding="utf-8")
    cfg = {k: v for k, v in CFG.items()}
    [s] = build_sources({"sources": [{**cfg, "glob": "*.md", "exclude_files": ["skip.md"]}]}, base_dir=tmp_path)
    assert isinstance(s, MarkdownTableSource) and len(s.candidates()) == 3


def test_other_table_after_target_table_is_not_read_with_old_header(tmp_path):
    text = "| 日期 | 事件 |\n|---|---|\n| 2020-01-01 | 甲事 |\n\n| 品項 | 價格 |\n|---|---|\n| 2020-02-02 | 100 |\n"
    cands = _src(tmp_path, text, filter={}, exclude={}, item_col=None, item_map=None).candidates()
    assert [c["title"] for c in cands] == ["甲事"]


def test_filter_is_required_and_item_map_order_matters(tmp_path):
    extra = "| 2019-07-07 | 一件不相干的事 | 爸 | 其他 |\n| 2019-08-08 | 兩個類型都有 | 爸 | 生日/家族大事 |\n"
    text = TIMELINE.replace("| 待定 |", extra + "| 待定 |")
    cands = _src(tmp_path, text).candidates()
    titles = [c["title"] for c in cands]
    assert "一件不相干的事" not in titles                            # 類型不在 filter 裡
    both = next(c for c in cands if c["title"] == "兩個類型都有")
    assert both["item"] == "生日送禮"                               # item_map 照設定順序，先中先贏
    swapped = _src(tmp_path, text, item_map={"家族大事": "家人大事", "生日": "生日送禮"}).candidates()
    assert next(c for c in swapped if c["title"] == "兩個類型都有")["item"] == "家人大事"


def test_empty_title_skipped_evidence_is_the_row_and_source_is_relative(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "t.md").write_text("| 日期 | 事件 |\n|---|---|\n| 2020-01-01 |  |\n| 2020-02-02 | 有標題的事 |\n", encoding="utf-8")
    src = MarkdownTableSource({**CFG, "files": [str(sub / "t.md")], "root": str(tmp_path), "filter": {}, "exclude": {},
                               "item_col": None, "item_map": None})
    [c] = src.candidates()
    assert c["title"] == "有標題的事" and c["source"] == "sub/t.md:4"
    assert c["evidence"] == "| 2020-02-02 | 有標題的事 |"
