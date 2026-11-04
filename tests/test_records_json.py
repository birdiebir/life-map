r"""records_json 來源（紀錄中心的健身 JSON）。全部用假資料。"""
import json

from lifemap.ach_sources import RecordsJsonSource, TrainingLogSource, build_sources


def rec(d, cat, w=None, status="done", archived=False):
    return {"date": d, "status": status, "archived": archived, "categoryRaw": cat,
            "exercises": [{"sets": [{"weightKg": w}]}]}


def src(tmp_path, items, **over):
    p = tmp_path / "fs.json"
    p.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    cfg = {"type": "records_json", "name": "假", "domain": "sports", "files": [str(p)], "root": str(tmp_path),
           "item_map": {"羽球": "羽球", "重量": "重訓"}, **over}
    return RecordsJsonSource(cfg)


def by(c):
    return {x["item"]: x for x in c}


def test_levels_same_rules_as_training_log(tmp_path):
    items = [rec(d, "羽球") for d in ["2026-01-05", "2026-01-12", "2026-01-19"]]       # 3 週、期間短 → 2
    items += [rec("2026-02-02", "重量")]                                              # 不到 3 週 → 1
    items += [rec(d, "x羽球") for d in ["2026-05-04", "2026-06-01", "2026-07-06"]]    # 加長期間：01-05～07-06 但涵蓋率低
    b = by(src(tmp_path, items).candidates())
    assert b["重訓"]["level"] == "1" and b["重訓"]["date"] == "2026-02-02"
    assert b["羽球"]["level"] == "2"                       # 6 週有紀錄 ÷ 27 週 < 0.5
    assert b["羽球"]["source"] == "fs.json#羽球" and b["羽球"]["origin"] == "training_log"
    assert "共 6 週" in b["羽球"]["evidence"]


def test_high_coverage_long_span_gets_level_3_and_5(tmp_path):
    from datetime import date, timedelta
    d0 = date(2026, 1, 5)
    ds3 = [(d0 + timedelta(weeks=i)).isoformat() for i in range(14)]          # 14 週連續 → 3
    assert by(src(tmp_path, [rec(d, "羽球") for d in ds3]).candidates())["羽球"]["level"] == "3"
    ds5 = [(d0 + timedelta(weeks=i)).isoformat() for i in range(54)]          # 54 週連續 → 5
    assert by(src(tmp_path, [rec(d, "羽球") for d in ds5]).candidates())["羽球"]["level"] == "5"


def test_filters_archived_status_and_bad_dates(tmp_path):
    items = [rec("2026-01-05", "羽球", archived=True), rec("2026-01-06", "羽球", status="planned"),
             rec("壞日期", "羽球"), rec("2026-01-07", "休息"), rec("2026-01-08", "羽球")]
    s = src(tmp_path, items)
    c = s.candidates()
    assert [x["date"] for x in c] == ["2026-01-08"]
    assert s.skipped == {"封存或狀態不符": 2, "日期無法辨識": 1, "類別對不到項目": 1}


def test_status_setting(tmp_path):
    items = [rec("2026-01-05", "羽球", status="planned")]
    assert src(tmp_path, items).candidates() == []
    assert len(src(tmp_path, items, status=["planned"]).candidates()) == 1


def test_infer_by_load(tmp_path):
    items = [rec("2026-01-05", None, 30), rec("2026-01-06", "執行日誌", None)]
    assert src(tmp_path, items).candidates() == []
    b = by(src(tmp_path, items, infer_by_load=True).candidates())
    assert sorted(b) == ["徒手訓練", "重訓"]
    b = by(src(tmp_path, items, infer_by_load=True, load_item="負重", bodyweight_item="徒手").candidates())
    assert sorted(b) == ["徒手", "負重"]


def test_evidence_has_no_content_and_title(tmp_path):
    c = src(tmp_path, [rec("2026-01-05", "羽球", 99)]).candidates()[0]
    assert "99" not in c["evidence"] and c["title"] == "羽球訓練紀錄"


def test_non_dict_json_and_build_sources(tmp_path):
    p = tmp_path / "fs.json"
    p.write_text("[]", encoding="utf-8")
    s = build_sources({"sources": [{"type": "records_json", "name": "a", "domain": "sports",
                                    "files": ["fs.json"], "item_map": {}}]}, base_dir=tmp_path)[0]
    assert isinstance(s, RecordsJsonSource) and s.candidates() == []


def test_training_log_unchanged_by_refactor():
    assert TrainingLogSource.candidates is not RecordsJsonSource.candidates
