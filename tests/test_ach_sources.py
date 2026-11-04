"""Task 3：來源骨架（CsvSource、MarkdownSource、build_sources、候選 ID 穩定）。"""
from lifemap.ach_sources import CsvSource, MarkdownSource, build_sources, candidate_id
from lifemap.achievements import ACH_FIELDS


def _milestones(tmp_path):
    p = tmp_path / "m.csv"
    p.write_bytes("里程碑,計畫日期,實際日期,狀態,來源\r\n入職測試公司,2021-09-01,2021-09-06,已達成,KB/a.md\r\n"
                  "計畫中的事,2030-01-01,,計畫中,KB/b.md\r\n通過測試,2021-05-01,2021/06/07,已達成,KB/c.md\r\n"
                  .encode("utf-8-sig"))
    return p


CSV_CFG = {"type": "csv", "name": "career", "domain": "career", "item": "測試職涯",
           "columns": {"title": "里程碑", "date": "實際日期", "source": "來源"},
           "filter": {"狀態": "已達成"}}


def test_csv_source_filters_and_maps_columns(tmp_path):
    src = CsvSource({**CSV_CFG, "path": str(_milestones(tmp_path))})
    cands = src.candidates()
    assert [c["title"] for c in cands] == ["入職測試公司", "通過測試"]
    c = cands[0]
    assert c["domain"] == "career" and c["item"] == "測試職涯" and c["date"] == "2021-09-06"
    assert c["source"] == "KB/a.md" and c["origin"] == "csv" and c["confirmed"] == "false"
    assert cands[1]["date"] == "2021-06-07"            # 2021/06/07 正規化
    assert set(ACH_FIELDS) <= set(c)


def test_csv_source_filter_in_list(tmp_path):
    cfg = {**CSV_CFG, "path": str(_milestones(tmp_path)), "filter": {"狀態": ["已達成", "計畫中"]}}
    assert len(CsvSource(cfg).candidates()) == 3


def test_candidate_ids_stable_across_runs(tmp_path):
    cfg = {**CSV_CFG, "path": str(_milestones(tmp_path))}
    a = [c["achievement_id"] for c in CsvSource(cfg).candidates()]
    b = [c["achievement_id"] for c in CsvSource(cfg).candidates()]
    assert a == b and all(i.startswith("A-") and len(i) == 12 for i in a) and len(set(a)) == 2


def test_candidate_id_ignores_line_number():
    assert candidate_id("learning", "kb_note", "a.md:3", "T") == candidate_id("learning", "kb_note", "a.md:9", "T")
    assert candidate_id("learning", "kb_note", "a.md:3", "T") != candidate_id("career", "kb_note", "a.md:3", "T")


NOTE = """# 標題
說明文字沒有日期
- 2023-04-15 考過測試證照 A
- 沒有日期的條列
* 完成測試課程（2022 年 3 月）
| 項目 | 日期 |
|---|---|
| 通過測試檢定 | 2019-07 |
| 無日期列 | 待定 |
2023-01-01 這行不是條列也不是表格
"""


def _note(tmp_path):
    p = tmp_path / "kb" / "教育" / "note.md"
    p.parent.mkdir(parents=True)
    p.write_text(NOTE, encoding="utf-8")
    return p


def test_markdown_only_dated_lines_with_line_numbers(tmp_path):
    p = _note(tmp_path)
    src = MarkdownSource({"type": "markdown", "name": "kb", "domain": "learning", "item": "測試",
                          "root": str(tmp_path / "kb"), "files": [str(p)]})
    cands = src.candidates()
    assert len(cands) == 3
    by_title = {c["title"]: c for c in cands}
    assert by_title["考過測試證照 A"]["date"] == "2023-04-15"
    assert by_title["考過測試證照 A"]["source"] == "教育/note.md:3"
    assert by_title["完成測試課程"]["date"] == "2022-03"
    assert by_title["通過測試檢定"]["date"] == "2019-07"
    assert by_title["通過測試檢定"]["source"].endswith(":8")
    assert all(c["origin"] == "kb_note" and c["evidence"] for c in cands)


def test_markdown_glob_and_exclude(tmp_path):
    p = _note(tmp_path)
    (p.parent / "README.md").write_text("- 2020-01-01 不該抓\n", encoding="utf-8")
    cfg = {"type": "markdown", "name": "kb", "domain": "learning", "item": "測試", "root": str(tmp_path / "kb"),
           "glob": str(tmp_path / "kb" / "教育" / "*.md"), "exclude": ["README.md"]}
    titles = [c["title"] for c in MarkdownSource(cfg).candidates()]
    assert "不該抓" not in titles and len(titles) == 3


def test_markdown_ids_stable_when_lines_shift(tmp_path):
    p = _note(tmp_path)
    cfg = {"type": "markdown", "name": "kb", "domain": "learning", "item": "測試", "root": str(tmp_path / "kb"),
           "files": [str(p)]}
    a = sorted(c["achievement_id"] for c in MarkdownSource(cfg).candidates())
    p.write_text("新增一行\n" + NOTE, encoding="utf-8")
    b = sorted(c["achievement_id"] for c in MarkdownSource(cfg).candidates())
    assert a == b


def test_build_sources_from_config(tmp_path):
    cfg = {"sources": [{**CSV_CFG, "path": "m.csv"}]}
    _milestones(tmp_path)
    srcs = build_sources(cfg, base_dir=tmp_path)          # 相對路徑以設定檔所在資料夾為準
    assert srcs[0].name == "career" and len(srcs[0].candidates()) == 2


def test_same_title_different_date_not_collapsed(tmp_path):
    p = tmp_path / "kb" / "n.md"
    p.parent.mkdir(parents=True)
    p.write_text("- 2020-01 年度表揚\n- 2021-01 年度表揚\n", encoding="utf-8")
    cfg = {"type": "markdown", "name": "kb", "domain": "career", "item": "x", "root": str(tmp_path / "kb"),
           "files": [str(p)]}
    c = MarkdownSource(cfg).candidates()
    assert len(c) == 2 and c[0]["achievement_id"] != c[1]["achievement_id"]
    ids = sorted(x["achievement_id"] for x in c)
    p.write_text("插一行\n- 2020-01 年度表揚\n- 2021-01 年度表揚\n", encoding="utf-8")
    assert sorted(x["achievement_id"] for x in MarkdownSource(cfg).candidates()) == ids


def test_csv_same_title_blank_source_different_date(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("里程碑,實際日期,來源\n年度表揚,2020-01,\n年度表揚,2021-01,\n", encoding="utf-8")
    cfg = {"type": "csv", "name": "c", "domain": "career", "item": "x", "path": str(p),
           "columns": {"title": "里程碑", "date": "實際日期", "source": "來源"}}
    c = CsvSource(cfg).candidates()
    assert len(c) == 2 and c[0]["achievement_id"] != c[1]["achievement_id"]
