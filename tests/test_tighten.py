r"""來源收緊：表格表頭不當候選、first_table_only、相簿日期優先序、日誌/健身去重、自動填 n、足跡同批去重。全部假資料。"""
from lifemap.ach_sources import MarkdownSource


# ---------- 5. 只讀第一張表、表頭不當候選 ----------
def test_markdown_skips_table_header_and_reads_first_table_only(tmp_path):
    p = tmp_path / "tools.md"
    p.write_text(
        "| 工具 | 用途 | 狀態（截至 2026-10-21） |\n|---|---|---|\n"
        "| tool-alpha | 檢查 | 2026-10-13 結案 |\n| tool-beta | 索引 | 2026-10-14 結案 |\n\n"
        "## 2. 其他\n\n- 2026-10-20 結案 條列不該讀\n\n"
        "| 工具 | 專案結案 |\n|---|---|\n| tool-gamma | 2026-10-21 結案 |\n", encoding="utf-8")
    base = {"name": "t", "files": [str(p)], "domain": "learning", "item": "side project", "require_any": ["結案"]}
    allc = MarkdownSource(base).candidates()
    assert "工具" not in {c["title"] for c in allc}                       # 表頭永遠不當候選
    assert {c["title"] for c in allc} >= {"tool-alpha", "tool-beta", "tool-gamma"}
    first = MarkdownSource({**base, "first_table_only": True}).candidates()
    assert {c["title"] for c in first} == {"tool-alpha", "tool-beta"}   # 第二張表與條列都不讀


# ---------- 6. 相簿日期：名稱日期優先、不用上傳日／修改日 ----------
import csv

from lifemap.ach_sources_ext import PhotoAlbumSource, group_albums, name_date


def test_name_date_formats():
    assert name_date("小明畢業典禮1030620") == "2014-06-20"           # 民國 7 碼
    assert name_date("1080913-4 中秋佳節") == "2019-09-13"
    assert name_date("20160312某商場公演ABC") == "2016-03-12"   # 西元 8 碼
    assert name_date("Me/國小/2014-06-23_畢業典禮") == "2014-06-23"     # 資料夾看最後一層
    assert name_date("Me/2013-11-17_範例班遊/其他") == ""                # 最後一層沒日期
    assert name_date("1061317 壞日期") == "" and name_date("IMG 9991001") == ""   # 月份不合法、年份不在 80～130
    assert name_date("CityA 2024 (G)") == "" and name_date("Graduation Ceremony") == ""


CAT_FIELDS = ["file_id", "folder", "line_album", "date_taken", "date_precision", "date_source", "drive_modified"]


def _catalog(tmp_path, rows):
    p = tmp_path / "cat.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAT_FIELDS)
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({"file_id": str(i), "folder": "", "line_album": "", "date_taken": "", "date_precision": "",
                        "date_source": "", "drive_modified": "", **r})
    return p


def test_album_name_date_beats_photo_dates_and_upload_dates_are_ignored(tmp_path):
    rows = []
    for i in range(6):   # 名稱有日期，照片拍攝日是別天 → 用名稱
        rows.append({"line_album": "1030620 畢業典禮", "date_taken": "2014-06-23", "date_precision": "day", "date_source": "EXIF"})
    for i in range(6):   # 無名稱日期；拍攝日 = 雲端修改日（檔名時間戳）→ 不用；
        rows.append({"line_album": "畢業典禮B", "date_taken": "2026-09-12", "date_precision": "day", "date_source": "檔名",
                     "drive_modified": "2026-09-12T10:00:00"})
    for i in range(6):   # 無名稱日期；EXIF 拍攝日 → 用拍攝日
        rows.append({"line_album": "畢業典禮C", "date_taken": "2016-05-01", "date_precision": "day", "date_source": "EXIF",
                     "drive_modified": "2016-05-01T10:00:00"})
    cat = _catalog(tmp_path, rows)
    groups, _ = group_albums({"catalog": str(cat), "group_by": "line_album", "min_photos": 5})
    by = {g["key"]: g for g in groups}
    assert (by["1030620 畢業典禮"]["ds"], by["1030620 畢業典禮"]["precision"]) == ("2014-06-20", "name")
    assert by["畢業典禮B"]["ds"] == "" and by["畢業典禮B"]["precision"] == "none"   # 上傳日不當事件日期
    assert by["畢業典禮C"]["ds"] == "2016-05-01" and by["畢業典禮C"]["precision"] == "day"
    c = PhotoAlbumSource({"name": "a", "catalog": str(cat), "group_by": "line_album", "min_photos": 5, "domain": "social",
                          "item": "活動", "rules": [{"match": "畢業典禮", "domain": "learning", "item": "國小"}]}).candidates()
    assert {x["title"]: x["date"] for x in c}["1030620 畢業典禮"] == "2014-06-20"


# ---------- 7. 主檔已涵蓋的同領域同項目、等級不低於候選的，不產生候選 ----------
from lifemap.ach_sources import drop_covered_by_main


def _r(domain, item, level, **kw):
    return {"achievement_id": f"A-{domain}{item}{level}", "domain": domain, "item": item, "level": level, **kw}


def test_drop_covered_by_main_levels():
    main = [_r("sports", "重訓", "2", confirmed="true"), _r("sports", "羽球", "3", confirmed="false"),
            _r("learning", "學士", "", confirmed="true")]
    rows = [_r("sports", "重訓", "1"), _r("sports", "重訓", "2"), _r("sports", "重訓", "3"),   # 低、同、高
            _r("sports", "羽球", "1"),                                                         # 主檔那筆沒確認，不算
            _r("sports", "徒手訓練", "1"),                                                     # 沒有同項目
            _r("learning", "學士", ""), _r("family", "重訓", "1")]                              # 沒等級的不動；別的領域不動
    kept, n = drop_covered_by_main(rows, main)
    assert n == 2
    assert [(r["domain"], r["item"], r["level"]) for r in kept] == [
        ("sports", "重訓", "3"), ("sports", "羽球", "1"), ("sports", "徒手訓練", "1"), ("learning", "學士", ""), ("family", "重訓", "1")]
    assert drop_covered_by_main(rows, [])[1] == 0


def test_journal_require_any_keeps_only_milestone_rows(tmp_path):
    p = tmp_path / "2026-09.md"
    p.write_text("| 日期 | 今日最重要的里程碑 |\n|---|---|\n| 2026-09-02 | 打了羽球比賽 |\n"
                 "| 2026-09-18 | 第一件報告被核准 |\n| 2026-09-14 | 差一堂課完成線上課程 |\n", encoding="utf-8")
    from lifemap.ach_sources import MarkdownTableSource
    c = MarkdownTableSource({"name": "j", "files": [str(p)], "date_col": "日期", "title_cols": ["今日最重要的里程碑"],
                             "domain": "career", "item": "乙公司", "match_on": "title",
                             "require_any": ["核准", "里程碑"], "drop_any": ["差一堂"]}).candidates()
    assert [x["date"] for x in c] == ["2026-09-18"]


# ---------- 8. 疑似重複對到「已決定不收」的舊列，這次 suggest 也是 n → 直接自動填 n ----------
from lifemap.ach_pending import auto_decide, is_auto
from test_auto_decide import by, cand, pend


def test_dup_of_refused_row_with_suggest_n_is_auto_n(tmp_path):
    p = pend(tmp_path, [
        cand("A-old", title="課程作業心得", decision="n"),
        cand("A-new1", title="課程作業心得！", suggest="n", certainty="高"),       # 對到不收、suggest n → 自動 n
        cand("A-new2", title="課程作業心得", suggest="n", certainty="低", source="x.md:1"),   # 把握度低也一樣直接填 n
        cand("A-keep", title="另一件事", decision="y"),
        cand("A-new3", title="另一件事！", suggest="n", certainty="高"),           # 對到的是已收的 → 仍是疑似重複，問使用者
        cand("A-new4", title="課程作業心得 ", suggest="y", certainty="高"),         # 對到不收但這次 suggest y → 仍問使用者
    ])
    res = auto_decide(p)
    b = by(p)
    for i in ("A-new1", "A-new2"):
        assert (b[i]["decision"], b[i]["auto"]) == ("n", "n") and is_auto(b[i]) and "同於已決定不收的 A-old" in b[i]["reason"]
    assert b["A-new3"]["decision"] == "" and b["A-new3"]["certainty"] == "低" and "疑似重複：A-keep" in b["A-new3"]["reason"]
    assert b["A-new4"]["decision"] == "" and "疑似重複：A-old" in b["A-new4"]["reason"]
    assert res["auto_n"] == 2 and res["suspected_dup"] == 2 and res["auto_y"] == 0


def test_dup_auto_n_respects_user_withdrawal_and_social_origin(tmp_path):
    p = pend(tmp_path, [
        cand("A-old", title="課程作業心得", decision="n"),
        cand("A-w", title="課程作業心得", suggest="n", certainty="高", auto="n"),               # 自動填過、使用者清空＝撤回，不再自動填
        cand("A-fb", title="課程作業心得", suggest="n", certainty="高", origin="fb_group_admin"),   # 社群來源永不自動
    ])
    res = auto_decide(p)
    b = by(p)
    assert b["A-w"]["decision"] == "" and b["A-fb"]["decision"] == "" and res["auto_n"] == 0
    assert auto_decide(p)["auto_n"] == 0                                                       # 重跑結果不變


# ---------- 9. 足跡同一批新候選互相重複只留一筆 ----------
from lifemap.place_events import BATCH_LABEL, build_rows, dedupe_batch


def _pr(pid, ds, de, level="3", conf="中", vid=None):
    return {"visit_id": vid or f"P{pid}{ds}{de}", "place_id": pid, "date_start": ds, "date_end": de, "level": level, "confidence": conf}


def test_dedupe_batch_same_place_overlapping_dates():
    rows = [_pr("C-JPN", "2025-01-15", "2025-01-19", "4", "中"),
            _pr("C-JPN", "2025-01-17", "", "3", "中"),                 # 同地點、日期重疊、等級較低 → 去掉
            _pr("C-JPN", "2025-03-01", "", "3", "低"),                 # 不重疊 → 留
            _pr("C-NZL", "2025-01-17", "", "3", "低"),                 # 不同地點 → 留
            _pr("C-FRA", "2012", "", "3", "低"), _pr("C-FRA", "2012-07", "", "3", "中")]  # 同級：留信心高的（月在年內算重疊）
    out, n = dedupe_batch(rows)
    assert n == 2
    assert [(r["place_id"], r["date_start"], r["confidence"]) for r in out] == [
        ("C-JPN", "2025-01-15", "中"), ("C-JPN", "2025-03-01", "低"), ("C-NZL", "2025-01-17", "低"), ("C-FRA", "2012-07", "中")]


def test_build_rows_dedupes_across_sources_in_same_batch(tmp_path):
    from test_sources_ext import catalog, place_cfgs, real_places
    cfgs = place_cfgs(tmp_path)
    sub = tmp_path / "b"
    sub.mkdir()
    cat2 = catalog(sub, [("Japan 2025", "", "2025-01-17", "day")] * 3)             # 另一個來源也出日本，日期落在第一個裡面
    other = {"type": "album_places", "label": "第二個來源", "catalog": str(cat2), "group_by": "folder", "min_photos": 3,
             "origin": "album2", "rules": [{"match": "Japan", "place_id": "C-JPN", "level": 3}]}
    rows, report = build_rows([cfgs[0], other], real_places(), [])
    jp = [r for r in rows if r["place_id"] == "C-JPN"]
    assert len(jp) == 1 and (jp[0]["date_start"], jp[0]["level"]) == ("2025-01-15", "4")     # 留等級高的那筆
    assert (BATCH_LABEL, 1, 0, {}) in report
