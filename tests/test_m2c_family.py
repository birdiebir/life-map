r"""M2-c：include_any／item_rules、trips 來源、併進旅程、雙向連結、apply 腳本、訓練標題小修。全部假資料。"""
import json
import subprocess
import sys

import pytest

from lifemap.ach_sources import (MarkdownTableSource, TrainingLogSource, TripSource, absorb_trip_duplicates,
                                 build_sources)
from lifemap.achievements import ACH_FIELDS

from tests._ach import ROOT, HEADER, make_domains

TIMELINE = """| 日期 | 事件 | 人物 | 類型 |
|---|---|---|---|
| 2019-03-02 | 全家去甲地過年 | 爸 | 家族大事 |
| 2019-04-10 | 陪爸去醫院辦手續 | 爸 | 健康 |
| 2019-05-01 | 幫媽規劃退休帳戶 | 媽 | 財務 |
| 2019-06-01 | 教媽用手機 | 媽 | 日常 |
| 2019-07-01 | 隨便吃個飯 | 媽 | 日常 |
| 2019-08-01 | 協助爸搬家 | 爸 | 家族大事 |
"""
KW = "事件"
BASE = {"type": "md_table", "name": "時間軸", "domain": "family", "item": "家人大事", "date_col": "日期",
        "title_cols": ["事件"], "filter": {"類型": ["家族大事"]}, "exclude": {"類型": ["財務", "健康"]}}


def _md(tmp_path, **over):
    p = tmp_path / "t.md"
    p.write_text(TIMELINE, encoding="utf-8")
    return MarkdownTableSource({**BASE, "files": [str(p)], "root": str(tmp_path), **over})


def _titles(cands):
    return [c["title"] for c in cands]


# ---------- 1. include_any／item_rules ----------
def test_include_any_adds_rows_exclude_still_wins(tmp_path):
    base = _titles(_md(tmp_path).candidates())
    assert base == ["全家去甲地過年", "協助爸搬家"]
    got = _titles(_md(tmp_path, include_any=[{KW: ["教媽", "規劃"]}]).candidates())
    # 「教媽用手機」類型不符但事件含關鍵字 → 收；「幫媽規劃」類型是財務，exclude 優先 → 不收
    assert got == ["全家去甲地過年", "教媽用手機", "協助爸搬家"]


def test_include_any_needs_every_column_in_one_rule(tmp_path):
    got = _titles(_md(tmp_path, include_any=[{KW: ["教媽"], "人物": ["爸"]}]).candidates())
    assert "教媽用手機" not in got          # 人物是媽，同一條規則的兩欄要同時成立
    got = _titles(_md(tmp_path, include_any=[{KW: ["教媽"], "人物": ["媽"]}]).candidates())
    assert "教媽用手機" in got
    got = _titles(_md(tmp_path, include_any=[{KW: ["沒有"]}, {KW: ["教媽"]}]).candidates())
    assert "教媽用手機" in got              # 任何一條成立即可


def test_include_any_alone_does_not_loosen_unrelated_rows(tmp_path):
    got = _titles(_md(tmp_path, include_any=[{KW: ["教媽"]}]).candidates())
    assert "隨便吃個飯" not in got


def test_item_rules_before_item_map_first_match_wins(tmp_path):
    src = _md(tmp_path, include_any=[{KW: ["教媽"]}], item_col="類型", item_map={"家族大事": "家人大事"},
              item_rules=[{"col": KW, "contains": ["教媽", "協助"], "item": "幫助家人"},
                          {"col": KW, "contains": ["協助"], "item": "不該到這"}])
    by = {c["title"]: c["item"] for c in src.candidates()}
    assert by["教媽用手機"] == "幫助家人"
    assert by["協助爸搬家"] == "幫助家人"        # 比 item_map（家族大事→家人大事）優先，且先中先贏
    assert by["全家去甲地過年"] == "家人大事"     # 沒中 item_rules 才走 item_map


def test_item_rules_col_missing_or_no_hit_falls_back(tmp_path):
    src = _md(tmp_path, item_rules=[{"col": "不存在欄", "contains": ["全家"], "item": "X"}])
    assert {c["item"] for c in src.candidates()} == {"家人大事"}


# ---------- 2. trips 來源 ----------
TRIPS = ("trip_id,name,date_start,date_end,companions,kind,kb_link\n"
         "T1,春節旅行,2019-02-03,2019-02-08,爸、媽,家族旅遊,\n"
         "T2,獨旅,2019-09-01,2019-09-05,,旅行,\n"
         "T3,四月小旅行,2019-04,,媽,旅行,\n"
         "T4,沒日期,,,媽,家族旅遊,\n"
         "T5,同行有家人,2020,,爸,旅行,\n")


def _trips(tmp_path, **over):
    p = tmp_path / "trips.csv"
    p.write_text(TRIPS, encoding="utf-8")
    cfg = {"type": "trips", "name": "旅程", "path": str(p), "domain": "family", "filter": {"kind": ["家族旅遊"]}}
    cfg.update(over)
    return TripSource(cfg)


def test_trip_source_one_candidate_per_trip(tmp_path):
    src = _trips(tmp_path)
    c = src.candidates()
    assert len(c) == 1 and src.skipped == {"沒有開始日期": 1}
    c = c[0]
    assert set(ACH_FIELDS) <= set(c)
    assert (c["domain"], c["item"], c["title"], c["date"], c["origin"]) == ("family", "家族旅遊", "春節旅行",
                                                                        "2019-02-03", "trip")
    assert c["source"] == "trips.csv#T1" and c["confirmed"] == "false"
    assert c["evidence"] == "旅程 T1：2019-02-03～2019-02-08，同行：爸、媽"
    assert c["achievement_id"].startswith("A-")


def test_trip_source_include_any_and_partial_dates_and_item(tmp_path):
    src = _trips(tmp_path, include_any=[{"companions": ["爸"]}], item="家族出遊")
    got = {c["title"]: c for c in src.candidates()}
    assert set(got) == {"春節旅行", "同行有家人"}          # T4 沒日期略過、T3 同行是媽 → 不收
    assert got["同行有家人"]["date"] == "2020" and got["同行有家人"]["item"] == "家族出遊"
    assert got["同行有家人"]["evidence"] == "旅程 T5：2020～，同行：爸"
    src = _trips(tmp_path, filter={"kind": ["旅行"]})
    assert {c["title"] for c in src.candidates()} == {"獨旅", "四月小旅行", "同行有家人"}


def test_trip_source_stable_id_and_absorb_default(tmp_path):
    a = _trips(tmp_path).candidates()[0]["achievement_id"]
    assert a == _trips(tmp_path).candidates()[0]["achievement_id"]
    assert _trips(tmp_path).absorb_items == ["家人大事"]
    assert _trips(tmp_path, absorb_items=["家人大事", "生日送禮"]).absorb_items == ["家人大事", "生日送禮"]


def test_build_sources_resolves_trip_path_against_base(tmp_path):
    (tmp_path / "trips.csv").write_text(TRIPS, encoding="utf-8")
    (s,) = build_sources({"sources": [{"type": "trips", "path": "trips.csv", "domain": "family",
                                       "filter": {"kind": ["家族旅遊"]}}]}, base_dir=tmp_path)
    assert isinstance(s, TripSource) and len(s.candidates()) == 1


# ---------- 3. 同一趟只算一筆 ----------
def _row(title, date, item="家人大事", domain="family", origin="kb_table", evidence=""):
    r = {f: "" for f in ACH_FIELDS}
    r.update(title=title, date=date, item=item, domain=domain, origin=origin, evidence=evidence,
             achievement_id="A-" + title)
    return r


SPANS = {}


def _trip(date, end, tid="T9", title="旅程"):
    from lifemap.achievements import _bounds
    r = _row(title, date, item="家族旅遊", origin="trip", evidence=f"旅程 {tid}：{date}～{end}，同行：爸")
    SPANS[r["achievement_id"]] = (_bounds(date)[0], _bounds(end or date)[1])
    return r


def test_absorb_inside_period_and_boundaries():
    trip = _trip("2019-02-03", "2019-02-08")
    rows = [trip, _row("a前一天", "2019-02-02"), _row("b首日", "2019-02-03"), _row("c中間", "2019-02-05"),
            _row("d末日", "2019-02-08"), _row("e後一天", "2019-02-09")]
    kept, n = absorb_trip_duplicates(rows, ["家人大事"], SPANS)
    assert n == 3 and [r["title"] for r in kept] == ["旅程", "a前一天", "e後一天"]


def test_absorb_partial_dates_overlap_and_no_end():
    trip = _trip("2019-04", "")                       # 沒有 end → 整個 4 月
    rows = [trip, _row("三月底", "2019-03-31"), _row("四月初", "2019-04-01"), _row("四月底", "2019-04-30"),
            _row("五月", "2019-05"), _row("四月月份", "2019-04"), _row("整年", "2019")]
    kept, n = absorb_trip_duplicates(rows, ["家人大事"], SPANS)
    assert [r["title"] for r in kept] == ["旅程", "三月底", "五月"] and n == 4
    # YYYY 開始、沒有結束 → 整年
    kept, n = absorb_trip_duplicates([_trip("2019", ""), _row("年中", "2019-06-06"), _row("隔年", "2020-01-01")],
                                     ["家人大事"], SPANS)
    assert [r["title"] for r in kept] == ["旅程", "隔年"] and n == 1


def test_absorb_only_same_domain_item_listed_and_not_other_trips():
    rows = [_trip("2019-02-03", "2019-02-08"),
            _row("別領域", "2019-02-04", domain="career"),
            _row("別項目", "2019-02-04", item="生日送禮"),
            _row("沒日期", ""),
            _row("要併的", "2019-02-04"),
            _trip("2019-02-05", "2019-02-06", tid="T8", title="另一趟")]
    kept, n = absorb_trip_duplicates(rows, ["家人大事"], SPANS)
    assert n == 1
    assert [r["title"] for r in kept] == ["旅程", "別領域", "別項目", "沒日期", "另一趟"]
    kept, n = absorb_trip_duplicates(rows, ["家人大事", "生日送禮"], SPANS)
    assert n == 2 and "別項目" not in [r["title"] for r in kept]
    kept, n = absorb_trip_duplicates(rows, [], SPANS)
    assert n == 0 and len(kept) == len(rows)


def test_absorb_without_trips_is_noop_and_preserves_order():
    rows = [_row("x", "2019-01-01"), _row("y", "2019-01-02")]
    assert absorb_trip_duplicates(rows, ["家人大事"], SPANS) == (rows, 0)


def test_absorb_trip_without_span_is_ignored():
    t = _trip("2019-02-03", "2019-02-08")
    kept, n = absorb_trip_duplicates([t, _row("x", "2019-02-04")], ["家人大事"], {})
    assert n == 0 and len(kept) == 2


# ---------- 4. HTML payload 連結 ----------
def _setup_ach(tmp_path, source="trips.csv#T1"):
    row_ = ",".join(["A-1", "family", "家族旅遊", "春節旅行", "3", "2019-02-03", "false", "", "", source, "trip", "",
                     "true", "local", "false"]) + "\n"
    row2 = ",".join(["A-2", "family", "家人大事", "別的事", "2", "2019-03-01", "false", "", "", "x.md:3", "kb_table",
                     "", "true", "local", "false"]) + "\n"
    (tmp_path / "achievements.csv").write_text(HEADER + row_ + row2, encoding="utf-8")
    return tmp_path


def _fam_domains():
    from lifemap.achievements import load_domains
    lv = {str(i): f"L{i}" for i in range(6)}
    sc = {str(i): i for i in range(6)}
    return load_domains({"radar": {"top_n": 5}, "visited_min_level": 1, "privacy_levels": ["local"],
                         "domains": {"family": {"name": "家人", "levels": lv, "scores": sc, "recommend": False,
                                                "privacy": "local", "sets": []}}})


def _trips_dict():
    from lifemap.data import Trip
    return {"T1": Trip("T1", "春節旅行", "2019-02-03", "2019-02-08", "爸", "家族旅遊", "")}


def test_payload_card_has_trip_and_by_trip_links(tmp_path):
    from lifemap.ach_view import build_ach_payload
    p = build_ach_payload(_setup_ach(tmp_path), _fam_domains(), trips=_trips_dict())
    cards = {c["id"]: c for c in next(d for d in p["domains"] if d["id"] == "family")["cards"]}
    assert cards["A-1"]["trip"] == {"id": "T1", "name": "春節旅行"}
    assert "trip" not in cards["A-2"] or cards["A-2"]["trip"] is None
    assert p["by_trip"] == {"T1": [{"id": "A-1", "title": "春節旅行", "domain": "family"}]}
    y = p["by_year"][0]["cards"][0]
    assert y["id"] == "A-1" and y["trip"]["name"] == "春節旅行"


def test_payload_unknown_trip_or_no_trips_has_no_link(tmp_path):
    from lifemap.ach_view import build_ach_payload
    d = _setup_ach(tmp_path)
    p = build_ach_payload(d, _fam_domains())
    assert p["by_trip"] == {}
    p = build_ach_payload(d, _fam_domains(), trips={})
    assert p["by_trip"] == {}
    cards = next(x for x in p["domains"] if x["id"] == "family")["cards"]
    assert all(not c.get("trip") for c in cards)


def test_payload_source_must_be_trips_csv(tmp_path):
    from lifemap.ach_view import build_ach_payload
    d = _setup_ach(tmp_path, source="notes.csv#T1")
    assert build_ach_payload(d, _fam_domains(), trips=_trips_dict())["by_trip"] == {}


def test_payload_suppressed_card_not_linked(tmp_path):
    from lifemap.ach_view import build_ach_payload
    d = _setup_ach(tmp_path)
    (d / "achievement_suppress.json").write_text(json.dumps([{"domain": "family", "item": "家族旅遊"}]),
                                                 encoding="utf-8")
    assert build_ach_payload(d, _fam_domains(), trips=_trips_dict())["by_trip"] == {}


def test_payload_pending_preview_candidate_linked(tmp_path):
    from lifemap.ach_pending import PENDING_FIELDS
    from lifemap.ach_view import build_ach_payload
    d = tmp_path
    (d / "achievements.csv").write_text(HEADER, encoding="utf-8")
    rec = dict.fromkeys(PENDING_FIELDS, "")
    rec.update(achievement_id="A-9", domain="family", item="家族旅遊", title="待確認旅程", level="2", date="2019-02-03",
               source="trips.csv#T1", origin="trip", together="false", confirmed="false", suppressed="false",
               suggest="y")
    (d / "pending_achievements.csv").write_text(",".join(PENDING_FIELDS) + "\n"
                                                + ",".join(rec[f] for f in PENDING_FIELDS) + "\n", encoding="utf-8")
    assert build_ach_payload(d, _fam_domains(), trips=_trips_dict())["by_trip"] == {}
    p = build_ach_payload(d, _fam_domains(), trips=_trips_dict(), include_pending=True)
    assert p["by_trip"]["T1"][0]["id"] == "A-9"


def test_template_has_links():
    html = (ROOT / "lifemap" / "template.html").read_text(encoding="utf-8")
    assert "tripAchLinks(v.trip)" in html and "旅程：" in html and "家人成就：" in html and "by_trip" in html


# ---------- 5. config ----------
def test_config_family_core_set():
    from lifemap.achievements import load_domains_for
    d = load_domains_for(ROOT / "private.example")
    s = {x.id: x for x in d.by_id["family"].sets}["family_core"]
    assert s.name == "家人" and list(s.items) == ["家人大事", "生日送禮", "幫助家人", "家族旅遊"]


# ---------- 6. 範例端到端 ----------
def test_example_family_flow():
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "import_achievements.py"),
                        "--dry-run", "--example"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "family／幫助家人" in out and "family／家族旅遊" in out
    assert "併進旅程 1 筆" in out


# ---------- 8. 訓練標題小修 ----------
def _train(tmp_path, item_map):
    p = tmp_path / "n.md"
    p.write_text("| 日期 | 類別 | 內容 |\n|---|---|---|\n| 2026-01-05 | 徒手 | a |\n| 2026-01-06 | 羽球 | b |\n",
                 encoding="utf-8")
    return TrainingLogSource({"domain": "sports", "files": [str(p)], "root": str(tmp_path), "date_col": "日期",
                              "category_col": "類別", "item_map": item_map})


def test_training_title_not_doubled(tmp_path):
    by = {c["item"]: c["title"] for c in _train(tmp_path, {"徒手": "徒手訓練", "羽球": "羽球"}).candidates()}
    assert by["徒手訓練"] == "徒手訓練紀錄" and by["羽球"] == "羽球訓練紀錄"


# ---------- 9. apply 腳本 ----------
def _apply_dir(tmp_path):
    from lifemap.ach_pending import PENDING_FIELDS
    base = dict.fromkeys(PENDING_FIELDS, "")
    rows = []
    for i, dec in (("1", "y"), ("2", "n"), ("3", "")):
        r = dict(base, achievement_id=f"A-{i}", domain="learning", item="A", title=f"t{i}", level="2",
                 date="2024-01", together="false", confirmed="false", suppressed="false", decision=dec)
        rows.append(",".join(r[f] for f in PENDING_FIELDS))
    (tmp_path / "pending_achievements.csv").write_text(",".join(PENDING_FIELDS) + "\n" + "\n".join(rows) + "\n",
                                                       encoding="utf-8")
    (tmp_path / "achievements.csv").write_text(HEADER, encoding="utf-8")
    return tmp_path


def _run_apply(*args):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "apply_achievements.py"), *args],
                          capture_output=True, text=True, encoding="utf-8")


def test_apply_script_dry_run_then_write(tmp_path):
    d = _apply_dir(tmp_path)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    r = _run_apply("--data-dir", str(d))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "收 1 筆" in r.stdout and "留 2 筆" in r.stdout and "試跑" in r.stdout
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before          # dry-run 什麼都沒動
    r = _run_apply("--data-dir", str(d), "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "已寫入" in r.stdout and "收 1 筆" in r.stdout and "留 2 筆" in r.stdout
    assert "A-1" in (d / "achievements.csv").read_text(encoding="utf-8")
    assert "A-1" not in (d / "pending_achievements.csv").read_text(encoding="utf-8")


def test_apply_script_bad_decision_fails_without_writing(tmp_path):
    d = _apply_dir(tmp_path)
    p = d / "pending_achievements.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("\ny,", "\nmaybe,", 1), encoding="utf-8")
    before = {q.name: q.read_bytes() for q in d.iterdir()}
    r = _run_apply("--data-dir", str(d), "--write")
    assert r.returncode == 1 and "maybe" in r.stdout
    assert {q.name: q.read_bytes() for q in d.iterdir()} == before


def test_apply_script_missing_pending(tmp_path):
    r = _run_apply("--data-dir", str(tmp_path))
    assert r.returncode == 1 and "找不到" in r.stdout


def test_build_payload_links_trip_end_to_end(tmp_path):
    import shutil
    import paths
    from lifemap.achievements import load_domains_for
    from lifemap.build import build_payload
    d = tmp_path / "ex"
    shutil.copytree(ROOT / "private.example", d)
    a = d / "achievements.csv"
    a.write_text(a.read_text(encoding="utf-8").rstrip("\r\n") + "\n" + ",".join(
        ["A-trip", "family", "家族旅遊", "範例：家族過年旅行", "3", "2024-02-08", "false", "", "", "trips.csv#T04",
         "trip", "", "true", "local", "false"]) + "\n", encoding="utf-8")
    p = build_payload(d, paths.REFERENCE, paths.config("levels"), paths.config("sets"), paths.config("scoring"),
                      ach_domains=load_domains_for(d))
    assert p["ach"]["by_trip"]["T04"][0]["id"] == "A-trip" and p["trips"]["T04"]["name"] == "範例：家族過年旅行"
    fam = next(x for x in p["ach"]["domains"] if x["id"] == "family")
    assert next(c for c in fam["cards"] if c["id"] == "A-trip")["trip"]["id"] == "T04"


# ---------- 改壞抽查後補的測試 ----------
def test_training_title_only_exact_suffix_trimmed(tmp_path):
    by = {c["item"]: c["title"] for c in _train(tmp_path, {"徒手": "體能練", "羽球": "訓練"}).candidates()}
    assert by["體能練"] == "體能練訓練紀錄" and by["訓練"] == "訓練紀錄"


def test_absorb_items_explicit_empty_means_none(tmp_path):
    assert _trips(tmp_path, absorb_items=[]).absorb_items == []


def test_trip_without_name_is_skipped(tmp_path):
    p = tmp_path / "trips.csv"
    p.write_text("trip_id,name,date_start,date_end,companions,kind\nT1,,2019-01-01,,爸,家族旅遊\n", encoding="utf-8")
    src = TripSource({"path": str(p), "domain": "family", "filter": {"kind": ["家族旅遊"]}})
    assert src.candidates() == [] and src.skipped == {"沒有名稱": 1}


def test_trip_source_uses_actual_file_name(tmp_path):
    p = tmp_path / "my_trips.csv"
    p.write_text(TRIPS, encoding="utf-8")
    c = TripSource({"path": str(p), "domain": "family", "filter": {"kind": ["家族旅遊"]}}).candidates()
    assert c[0]["source"] == "my_trips.csv#T1"


def test_absorb_never_drops_another_trip_even_if_item_listed():
    other = _trip("2019-02-05", "2019-02-06", tid="T8", title="另一趟")
    other["item"] = "家人大事"
    kept, n = absorb_trip_duplicates([_trip("2019-02-03", "2019-02-08"), other], ["家人大事"], SPANS)
    assert n == 0 and len(kept) == 2


def test_absorb_span_only_applies_to_trip_origin_rows():
    fake = _row("非旅程列", "2019-02-03")                     # 即使 ID 剛好在 spans 裡，origin 不是 trip 就不當旅程
    victim = _row("被誤併", "2019-02-20")
    kept, n = absorb_trip_duplicates([fake, victim], ["家人大事"], {fake["achievement_id"]: ("2019-02-01", "2019-02-28")})
    assert n == 0 and len(kept) == 2


def test_payload_source_must_start_with_trips_csv(tmp_path):
    from lifemap.ach_view import build_ach_payload
    d = _setup_ach(tmp_path, source="old_trips.csv#T1")
    assert build_ach_payload(d, _fam_domains(), trips=_trips_dict())["by_trip"] == {}


def test_trip_candidates_twice_keeps_skip_count_and_dedupes_same_trip(tmp_path):
    src = _trips(tmp_path)
    src.candidates()
    src.candidates()
    assert src.skipped == {"沒有開始日期": 1}          # 重跑不累加
    p = tmp_path / "dup.csv"
    p.write_text("trip_id,name,date_start,date_end,companions,kind\n"
                 "T1,甲,2019-01-01,,爸,家族旅遊\nT1,甲,2019-01-01,,爸,家族旅遊\n", encoding="utf-8")
    assert len(TripSource({"path": str(p), "domain": "family", "filter": {"kind": ["家族旅遊"]}}).candidates()) == 1


# ---------- 查核後修正 ----------
def test_trip_date_end_invalid_or_before_start_treated_as_no_end(tmp_path):
    p = tmp_path / "trips.csv"
    p.write_text("trip_id,name,date_start,date_end,companions,kind\n"
                 "T1,斜線,2019-02-03,2019/02/08,爸,家族旅遊\n"
                 "T2,倒過來,2019-05-10,2019-05-01,爸,家族旅遊\n"
                 "T3,正常,2019-08-01,2019-08-03,爸,家族旅遊\n", encoding="utf-8")
    src = TripSource({"path": str(p), "domain": "family", "filter": {"kind": ["家族旅遊"]}})
    c = {x["title"]: x for x in src.candidates()}
    assert src.skipped == {"結束日期格式不對": 2}
    assert src.spans[c["斜線"]["achievement_id"]] == ("2019-02-03", "2019-02-03")
    assert src.spans[c["倒過來"]["achievement_id"]] == ("2019-05-10", "2019-05-10")
    assert src.spans[c["正常"]["achievement_id"]] == ("2019-08-01", "2019-08-03")
    rows = list(c.values()) + [_row("同年三月", "2019-03-05"), _row("十月", "2019-10-01"), _row("旅內", "2019-02-03")]
    kept, n = absorb_trip_duplicates(rows, ["家人大事"], src.spans)
    assert n == 1 and {r["title"] for r in kept} >= {"同年三月", "十月"}


def test_trip_skip_labels_split_missing_name_and_start(tmp_path):
    p = tmp_path / "trips.csv"
    p.write_text("trip_id,name,date_start,date_end,companions,kind\n"
                 "T1,,2019-01-01,,爸,家族旅遊\n"
                 "T2,有名,,,爸,家族旅遊\n"
                 "T3,壞日期,昨天,,爸,家族旅遊\n", encoding="utf-8")
    src = TripSource({"path": str(p), "domain": "family", "filter": {"kind": ["家族旅遊"]}})
    assert src.candidates() == [] and src.skipped == {"沒有名稱": 1, "沒有開始日期": 2}


def test_trip_spans_keyed_by_id_and_reset(tmp_path):
    src = _trips(tmp_path)
    (c,) = src.candidates()
    assert src.spans == {c["achievement_id"]: ("2019-02-03", "2019-02-08")}
    src.candidates()
    assert len(src.spans) == 1


def test_dedupe_across_prefers_trip_over_same_title_date_other_origin():
    from lifemap.ach_sources import dedupe_across
    note = _row("春節旅行", "2019-02-03", item="家人大事")
    trip = _trip("2019-02-03", "2019-02-08", title="春節旅行")
    out = dedupe_across([note, trip])
    assert out == [trip]                                   # 不論誰先出現，旅程那筆保留
    assert dedupe_across([trip, note]) == [trip]
    other = _row("別的", "2019-02-03")
    assert dedupe_across([other, note]) == [other, note]           # 沒有旅程時照舊
    assert dedupe_across([note, dict(note)]) == [note]


def test_trip_same_day_end_is_valid_and_spans_reset_when_file_changes(tmp_path):
    p = tmp_path / "trips.csv"
    p.write_text("trip_id,name,date_start,date_end,companions,kind\nT1,一日遊,2019-05-01,2019-05-01,爸,家族旅遊\n",
                 encoding="utf-8")
    src = TripSource({"path": str(p), "domain": "family", "filter": {"kind": ["家族旅遊"]}})
    (c,) = src.candidates()
    assert src.skipped == {} and src.spans[c["achievement_id"]] == ("2019-05-01", "2019-05-01")
    p.write_text("trip_id,name,date_start,date_end,companions,kind\nT2,別趟,2020-01-01,,爸,家族旅遊\n", encoding="utf-8")
    src.candidates()
    assert len(src.spans) == 1 and ("2020-01-01", "2020-01-01") in src.spans.values()


def test_apply_script_write_backs_up_achievements_with_timestamp(tmp_path):
    d = _apply_dir(tmp_path)
    before = (d / "achievements.csv").read_bytes()
    r = _run_apply("--data-dir", str(d), "--write")
    assert r.returncode == 0
    baks = list(d.glob("achievements.before_apply.*.csv"))
    assert len(baks) == 1 and baks[0].read_bytes() == before
