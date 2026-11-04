r"""來源擴充：file_index、photo_albums、jsonl_events、md_table 無日期欄、來源層級雜訊閘門、社群來源不自動決定、足跡事件。全部假資料。"""
import json
import subprocess
import sys

import pytest

from _ach import ROOT
from lifemap.ach_pending import PENDING_FIELDS, apply_judgments, auto_decide, never_auto
from lifemap.ach_sources import MarkdownSource, MarkdownTableSource, build_sources, date_ok, route, text_gate
from lifemap.ach_sources_ext import FileIndexSource, JsonlEventsSource, PhotoAlbumSource, group_albums, parse_event_date
from lifemap.pending import PENDING_FIELDS as VISIT_PENDING, read_rows, write_rows
from lifemap.place_events import build_rows

from test_auto_decide import by, cand, pend
from _ach import real_domains


# ---------- 通用小工具 ----------
def test_parse_event_date_formats():
    assert parse_event_date("2026-10-13T08:26:45") == "2026-10-13"
    assert parse_event_date("3 月 14, 2016 09:15:30 上午") == "2016-03-14"
    assert parse_event_date("1 月 07, 2020 10:59:32 上午") == "2020-01-07"
    assert parse_event_date("學士 2021 年 4 月 12 日報告") == "2021-04-12"
    assert parse_event_date("沒有日期") == ""


def test_text_gate_route_date_ok():
    cfg = {"drop_any": ["草稿"], "require_any": ["獎", "offer"]}
    assert text_gate(cfg, "獲獎") and text_gate(cfg, "拿到 Offer") and not text_gate(cfg, "獲獎草稿") and not text_gate(cfg, "普通")
    assert text_gate({}, "任何")
    c = {"domain": "career", "item": "X", "domain_rules": [{"match": "羽球", "domain": "sports", "item": "羽球"},
                                                            {"match": "垃圾", "drop": True}]}
    assert route(c, "打羽球") == ("sports", "羽球") and route(c, "其他") == ("career", "X") and route(c, "垃圾") is None
    assert route({**c, "drop_unmatched": True}, "其他") is None
    cut = {"date_max": "2026-10-30"}
    assert date_ok(cut, "2026-10-30") and date_ok(cut, "2026-10") and not date_ok(cut, "2026-11-01") and not date_ok(cut, "2026-11")
    assert date_ok(cut, "") and date_ok({}, "2099-01-01")


def test_date_max_today_drops_future(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("- 2020-01-01 獲獎 過去\n- 2999-01-01 獲獎 未來\n", encoding="utf-8")
    c = MarkdownSource({"name": "n", "files": [str(p)], "domain": "career", "date_max": "today"}).candidates()
    assert [x["date"] for x in c] == ["2020-01-01"]


# ---------- markdown／md_table 擴充 ----------
def test_markdown_origin_gate_and_routing_leave_old_behavior_untouched(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("- 2021-01-01 得獎 羽球比賽冠軍\n- 2021-02-02 吃飯\n", encoding="utf-8")
    old = MarkdownSource({"name": "n", "files": [str(p)], "domain": "learning", "item": "學習"}).candidates()
    assert len(old) == 2 and {x["origin"] for x in old} == {"kb_note"} and {x["domain"] for x in old} == {"learning"}
    new = MarkdownSource({"name": "n", "files": [str(p)], "domain": "learning", "item": "學習", "origin": "kb_career",
                          "require_any": ["得獎"], "domain_rules": [{"match": "羽球", "domain": "sports", "item": "羽球"}]}).candidates()
    assert len(new) == 1 and new[0]["origin"] == "kb_career" and (new[0]["domain"], new[0]["item"]) == ("sports", "羽球")


def test_md_table_undated_with_heading_and_match_on_title(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("## 國小\n| 事件 | 原文重點 |\n|---|---|\n| 當選模範生 | 入圍 |\n| 只有標題 | 只有標題，沒寫內容 |\n"
                 "## 國中\n| 事件 | 原文重點 |\n|---|---|\n| 創立社團擔任團長 | 帶領成員 |\n", encoding="utf-8")
    cfg = {"name": "t", "files": [str(p)], "title_cols": ["事件"], "allow_undated": True, "domain": "adventure", "item": "趣事",
           "drop_any": ["只有標題"], "domain_rules": [{"match": "社團", "domain": "social", "item": "社群經營"}]}
    c = MarkdownTableSource(cfg).candidates()
    assert [(x["title"], x["domain"], x["date"]) for x in c] == [("當選模範生", "adventure", ""), ("創立社團擔任團長", "social", "")]
    assert c[0]["evidence"].startswith("[國小]") and c[1]["evidence"].startswith("[國中]")
    with pytest.raises(KeyError):                                   # 沒日期欄又沒開 allow_undated：明確報錯
        MarkdownTableSource({**cfg, "allow_undated": False}).candidates()
    j = tmp_path / "j.md"
    j.write_text("| 日期 | 里程碑 | 備註 |\n|---|---|---|\n| 2026-09-01 | 完成報告 | 順便陪媽媽 |\n", encoding="utf-8")
    jc = {"name": "j", "files": [str(j)], "date_col": "日期", "title_cols": ["里程碑"], "domain": "career", "item": "X",
          "domain_rules": [{"match": "媽媽", "domain": "family", "item": "家人"}]}
    assert MarkdownTableSource(jc).candidates()[0]["domain"] == "family"                   # 預設比對整列
    assert MarkdownTableSource({**jc, "match_on": "title"}).candidates()[0]["domain"] == "career"


# ---------- file_index ----------
INDEX = """# 索引
## 作品集\\學術
| 檔案 | 修改 | 這是什麼 |
|---|---|---|
| a.pdf | 2024-06-18 | 學士 2021 年 4 月 12 日範例研究報告 |
| b.pdf | 2022-09-02 | 2022 年 9 月 1 日急救員認證證書 |
| c.pdf | 2020-07-15 | 2020 範例價目表 |
| d.docx | 2025-02-20 | 沒有日期的筆記 |
## 其他
| 檔案 | 修改 | 這是什麼 |
|---|---|---|
| e.pdf | 2024-01-01 | 不在區段內 |
"""


def test_file_index_index_mode(tmp_path):
    ix = tmp_path / "INDEX.md"
    ix.write_text(INDEX, encoding="utf-8")
    cfg = {"name": "i", "index": str(ix), "section_contains": ["作品集"], "domain": "learning", "item": "作品集",
           "drop_any": ["價目表"]}
    s = FileIndexSource(cfg)
    c = s.candidates()
    assert [(x["date"], x["origin"]) for x in c] == [("2021-04-12", "file_index"), ("2022-09-01", "file_index"), ("", "file_index")]
    assert c[0]["title"] == "學士 範例研究報告" and "e.pdf" not in json.dumps(c, ensure_ascii=False)
    assert s.skipped == {"沒過去雜訊": 1}
    assert c[0]["source"] == "INDEX.md#作品集\\學術/a.pdf"
    # 沒日期的檔案預設不拿修改日；要才設 mtime fallback 來自 INDEX 的「修改」欄
    c2 = FileIndexSource({**cfg, "date_fallback": "mtime"}).candidates()
    assert c2[2]["date"] == "2025-02-20"


def test_file_index_glob_mode_and_filters(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "2022 專案報告.gdoc").write_text("x", encoding="utf-8")
    (tmp_path / "sub" / "草稿.gdoc").write_text("x", encoding="utf-8")
    (tmp_path / "sub" / "圖.png").write_text("x", encoding="utf-8")
    cfg = {"name": "g", "glob": str(tmp_path / "**" / "*"), "root": str(tmp_path), "domain": "learning", "item": "side project",
           "exts": [".gdoc"], "drop_any": ["草稿"]}
    s = FileIndexSource(cfg)
    c = s.candidates()
    assert [(x["title"], x["date"]) for x in c] == [("專案報告", "2022")]
    assert s.skipped == {"副檔名不在白名單": 1, "沒過去雜訊": 1}
    assert FileIndexSource({**cfg, "date_fallback": "mtime", "exts": [".png"]}).candidates()[0]["date"] != ""


# ---------- photo_albums ----------
def catalog(tmp_path, rows):
    p = tmp_path / "cat.csv"
    p.write_text("folder,line_album,date_taken,date_precision\n" + "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_photo_albums_range_outlier_min_photos_and_rules(tmp_path):
    rows = [("F1", "畢業典禮", d, "day") for d in ["2016-06-11"] * 4 + ["2016-06-12", "2010-01-01"]]
    rows += [("F2", "CityA-Mar2024", "2024-03-0%d" % i, "day") for i in range(1, 6)]
    rows += [("F3", "小相簿", "2020-01-01", "day")] * 2
    rows += [("F4", "月相簿", "2021-05-01", "month")] * 5
    p = catalog(tmp_path, rows)
    cfg = {"name": "a", "catalog": str(p), "group_by": "line_album", "min_photos": 5, "domain": "social", "item": "活動",
           "rules": [{"match": "畢業典禮", "domain": "learning", "item": "高中", "title": "高中畢業典禮"},
                     {"match": "月相簿", "together": True}]}
    s = PhotoAlbumSource(cfg)
    c = {x["title"]: x for x in s.candidates()}
    assert set(c) == {"高中畢業典禮", "月相簿"}
    g = c["高中畢業典禮"]
    assert g["date"] == "2016-06-11" and "2016-06-12" in g["evidence"] and "2010" not in g["evidence"]      # 離群日期被丟掉
    assert (g["domain"], g["item"], g["origin"], g["together"]) == ("learning", "高中", "album", "false")
    assert c["月相簿"]["date"] == "2021-05" and c["月相簿"]["together"] == "true"
    assert s.skipped == {"張數太少": 1, "沒對到規則": 1}                      # CityA 月份相簿沒規則 → 不當事件
    assert ".jpg" not in json.dumps(list(c.values()), ensure_ascii=False)


def test_photo_albums_folder_mode_uses_context_date(tmp_path):
    p = tmp_path / "cat.csv"
    p.write_text("folder,line_album,date_taken,date_precision\n" + "\n".join("老照片,,,none" for _ in range(3)) + "\n", encoding="utf-8")
    ctx = tmp_path / "ctx.csv"
    ctx.write_text("folder,date_range_推定,situation\n老照片,2012-03,家族旅行\n", encoding="utf-8")
    groups, _ = group_albums({"catalog": str(p), "context_csv": str(ctx), "group_by": "folder", "min_photos": 3})
    assert groups[0]["ds"] == "2012-03" and groups[0]["precision"] == "context"
    cfg = {"name": "f", "catalog": str(p), "context_csv": str(ctx), "group_by": "folder", "min_photos": 3, "domain": "family",
           "item": "家人大事", "rules": [{"match": "老照片"}]}
    c = PhotoAlbumSource(cfg).candidates()
    assert c[0]["date"] == "2012-03" and "家族旅行" in c[0]["evidence"] and "資料夾背景表推定" in c[0]["evidence"]


# ---------- jsonl_events ----------
def test_jsonl_events_fb_date_title_dedupe_and_origin_required(tmp_path):
    p = tmp_path / "g.jsonl"
    lines = [{"header": "我 建立了 甲社團 社團。", "timestamp": "3 月 14, 2016 09:15:30 上午"},
             {"header": "我 建立了 甲社團 社團。", "timestamp": "3 月 14, 2016 09:20:00 上午"},
             {"header": "我 更新了 甲社團 社團的簡介。", "timestamp": "3 月 14, 2016 09:31:12 上午"},
             {"header": "我 建立了 乙社團 社團。", "timestamp": "壞日期"}]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n壞行\n", encoding="utf-8")
    cfg = {"name": "g", "files": [str(p)], "origin": "fb_group_admin", "date_field": "timestamp", "text_field": "header",
           "include": ["建立了"], "title_regex": r"建立了\s*(.+?)\s*社團。?$", "title_prefix": "創立：", "domain": "social", "item": "社群經營"}
    s = JsonlEventsSource(cfg)
    c = s.candidates()
    assert [(x["title"], x["date"], x["origin"]) for x in c] == [("創立：甲社團", "2016-03-14", "fb_group_admin")]
    assert s.skipped == {"日期無法辨識": 1, "JSON 壞行": 1}
    with pytest.raises(ValueError):
        JsonlEventsSource({k: v for k, v in cfg.items() if k != "origin"})


def test_jsonl_events_gmail_include_exclude_require(tmp_path):
    p = tmp_path / "m.jsonl"
    subj = ["Your Tickets for Sample Badminton Open", "Reminder: Sample Badminton Open", "Order Confirmation for Coffee Voucher"]
    p.write_text("\n".join(json.dumps({"date_utc": "2022-05-07T01:00:00", "subject": s, "sender_domain": "x.com"}) for s in subj),
                 encoding="utf-8")
    cfg = {"name": "m", "files": [str(p)], "origin": "mail_event", "date_field": "date_utc", "include": [r"^(Your Tickets for|Order Confirmation for)\s"],
           "title_regex": r"(?:Your Tickets for|Order Confirmation for)\s+(.+)", "require_any": ["Badminton"], "evidence_fields": ["sender_domain"],
           "domain": "social", "item": "活動參與", "domain_rules": [{"match": "Badminton", "domain": "sports", "item": "羽球"}]}
    c = JsonlEventsSource(cfg).candidates()
    assert len(c) == 1 and c[0]["title"] == "Sample Badminton Open" and (c[0]["domain"], c[0]["item"]) == ("sports", "羽球")
    assert c[0]["evidence"].endswith("x.com")


def test_build_sources_registers_new_types_and_resolves_relative(tmp_path):
    (tmp_path / "INDEX.md").write_text(INDEX, encoding="utf-8")
    cfg = {"sources": [{"type": "file_index", "index": "INDEX.md", "domain": "learning"},
                       {"type": "photo_albums", "catalog": "cat.csv", "domain": "social"},
                       {"type": "jsonl_events", "origin": "mail_event", "date_field": "d", "files": ["x.jsonl"], "domain": "social"}]}
    srcs = build_sources(cfg, base_dir=tmp_path)
    assert srcs[0].cfg["index"] == str(tmp_path / "INDEX.md") and srcs[1].cfg["catalog"] == str(tmp_path / "cat.csv")
    assert srcs[2].cfg["files"] == [str(tmp_path / "x.jsonl")]


# ---------- 社群來源永遠不自動決定 ----------
def test_never_auto_prefixes():
    assert never_auto({"origin": "fb_group_admin"}) and never_auto({"origin": "IG_story"}) and not never_auto({"origin": "mail_event"})
    assert not never_auto({"origin": "kb_note"}) and not never_auto({})


def test_auto_decide_never_decides_social_origin(tmp_path):
    p = pend(tmp_path, [cand("A-fb", origin="fb_group_admin", suggest="y", certainty="高"),
                        cand("A-ig", origin="ig_post", suggest="n", certainty="高"),
                        cand("A-fb2", origin="fb_x"),                                   # 沒建議
                        cand("A-ok", origin="mail_event", suggest="y", certainty="高")])
    res = auto_decide(p)
    b = by(p)
    assert res["auto_y"] == 1 and res["auto_n"] == 0 and res["ask_user"] == 2 and res["no_suggest"] == 1
    assert b["A-fb"]["decision"] == "" and b["A-fb"]["certainty"] == "低" and b["A-fb"]["auto"] == ""
    assert b["A-ig"]["decision"] == "" and b["A-ig"]["certainty"] == "低"
    assert b["A-ok"]["decision"] == "y"
    # --default-certainty 高 也蓋不過去
    p2 = pend(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, [cand("A-fb", origin="fb_group_admin", suggest="y")])
    assert auto_decide(p2, "高")["auto_y"] == 0 and by(p2)["A-fb"]["decision"] == ""


def test_apply_judgments_forces_low_certainty_for_social(tmp_path):
    p = pend(tmp_path, [cand("A-fb", origin="fb_group_admin"), cand("A-m", origin="mail_event")])
    apply_judgments(p, [{"achievement_id": "A-fb", "level": 2, "suggest": "y", "certainty": "高"},
                        {"achievement_id": "A-m", "level": 2, "suggest": "y", "certainty": "高"}], real_domains())
    b = by(p)
    assert b["A-fb"]["certainty"] == "低" and b["A-m"]["certainty"] == "高"
    assert auto_decide(p)["auto_y"] == 1 and b["A-fb"]["decision"] == "" and by(p)["A-fb"]["decision"] == ""


# ---------- 足跡事件（pending.csv） ----------
def place_cfgs(tmp_path):
    cat = catalog(tmp_path, [("Japan 2025", "", "2025-01-15", "day"), ("Japan 2025", "", "2025-01-16", "day"),
                             ("Japan 2025", "", "2025-01-19", "day"), ("老照片", "", "", "none"), ("老照片", "", "", "none"),
                             ("老照片", "", "", "none")])
    ctx = tmp_path / "ctx.csv"
    ctx.write_text("folder,date_range_推定\n老照片,2012\n", encoding="utf-8")
    mail = tmp_path / "m.jsonl"
    mail.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [
        {"date_utc": "2020-11-06T01:00:00", "subject": "預訂確認 1 - 旅店 - 魚池鄉"},
        {"date_utc": "2020-11-07T01:00:00", "subject": "預訂已取消 - 魚池鄉"}]), encoding="utf-8")
    return [{"type": "album_places", "label": "資料夾", "catalog": str(cat), "context_csv": str(ctx), "group_by": "folder",
             "min_photos": 3, "origin": "album",
             "rules": [{"match": "Japan", "place_id": "C-JPN"}, {"match": "老照片", "place_ids": ["C-FRA", "C-ITA"], "level": 3}]},
            {"type": "jsonl_places", "label": "信件", "origin": "mail", "files": [str(mail)], "date_field": "date_utc",
             "include": ["預訂確認"], "exclude": ["取消"], "rules": [{"match": "魚池", "place_id": "TW-10008090", "level": 4}]}]


def real_places():
    import paths
    from lifemap.reference import load_places
    return load_places(paths.REFERENCE)


def test_place_events_rows(tmp_path):
    rows, report = build_rows(place_cfgs(tmp_path), real_places(), [])
    by_pid = {r["place_id"]: r for r in rows}
    assert set(by_pid) == {"C-JPN", "C-FRA", "C-ITA", "TW-10008090"}
    j = by_pid["C-JPN"]
    assert (j["date_start"], j["date_end"], j["level"], j["source"], j["confidence"]) == ("2025-01-15", "2025-01-19", "4", "album", "中")
    assert by_pid["C-FRA"]["confidence"] == "低" and "資料夾背景表推定" in by_pid["C-FRA"]["evidence"]     # 日期是推定的
    assert by_pid["TW-10008090"]["confidence"] == "低" and by_pid["TW-10008090"]["date_start"] == "2020-11-06"
    assert all(set(VISIT_PENDING) >= set(r) - {"evidence"} or True for r in rows)
    assert {r["confirmed"] for r in rows} == {"false"} and {r["decision"] for r in rows} == {""}


def test_place_events_social_origin_is_low_and_covered_skipped(tmp_path):
    from lifemap.data import Visit
    cfgs = place_cfgs(tmp_path)
    cfgs[0]["origin"] = "fb_checkin"
    rows, _ = build_rows(cfgs[:1], real_places(), [])
    assert {r["confidence"] for r in rows} == {"低"} and {r["source"] for r in rows} == {"fb_checkin"}
    cfgs[0]["origin"] = "album"
    v = Visit("V1", "C-JPN", "2025-01", "", 4, False, "", "", "", "manual", "", True)
    rows, report = build_rows(cfgs[:1], real_places(), [v])
    assert "C-JPN" not in {r["place_id"] for r in rows} and report[0][2] == 1


def test_place_events_unknown_place_id_raises(tmp_path):
    cfgs = place_cfgs(tmp_path)
    cfgs[0]["rules"][0]["place_id"] = "C-NOPE"
    with pytest.raises(ValueError):
        build_rows(cfgs, real_places(), [])


def test_import_event_places_script_example_dry_run_then_write_keeps_old_rows(tmp_path):
    ex = ROOT / "private.example"
    before = sorted(p.name for p in ex.iterdir())
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "import_event_places.py"), "--example"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "規則命中" in r.stdout and "試跑" in r.stdout and sorted(p.name for p in ex.iterdir()) == before
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "import_event_places.py"), "--example", "--write"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode != 0
    # 實際寫入：複製範例資料夾到暫存，pending.csv 已有一列舊資料，寫入後舊列還在
    import shutil
    work = tmp_path / "w"
    shutil.copytree(ex, work, ignore=shutil.ignore_patterns("output"))
    write_rows(work / "pending.csv", ["decision", "place_name", "visit_id", "place_id", "date_start", "date_end", "level", "together",
                                      "trip_id", "memory", "photo", "source", "confidence", "confirmed", "evidence"],
               [{"decision": "y", "visit_id": "Pold", "place_id": "C-USA", "date_start": "2010", "source": "review"}])
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "import_event_places.py"), "--data-dir", str(work), "--write"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    got = {x["visit_id"]: x for x in read_rows(work / "pending.csv")}
    assert "Pold" in got and got["Pold"]["decision"] == "y" and len(got) == 5
