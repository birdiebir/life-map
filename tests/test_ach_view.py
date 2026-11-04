import json
import re

import paths
from lifemap.ach_pending import PENDING_FIELDS
from lifemap.ach_view import build_ach_payload
from lifemap.build import build_payload, render_html
from tests._ach import HEADER, make_domains, row

PHEAD = ",".join(PENDING_FIELDS) + "\n"


def _prow(_id, level="", decision="", suggest="", domain="learning", item="A", title="待確認卡", date="2024-05"):
    d = dict.fromkeys(PENDING_FIELDS, "")
    d.update(decision=decision, suggest=suggest, achievement_id=_id, domain=domain, item=item, title=title,
             level=level, date=date, together="false", confirmed="false", suppressed="false")
    return ",".join(d[f] for f in PENDING_FIELDS) + "\n"


def _setup(tmp_path, ach_rows=(), pend_rows=(), pend_header=PHEAD, suppress=None):
    (tmp_path / "achievements.csv").write_text(HEADER + "".join(ach_rows), encoding="utf-8")
    if pend_rows is not None:
        (tmp_path / "pending_achievements.csv").write_text(pend_header + "".join(pend_rows), encoding="utf-8")
    if suppress is not None:
        (tmp_path / "achievement_suppress.json").write_text(json.dumps(suppress), encoding="utf-8")
    return tmp_path


def _dom(p, did):
    return next(d for d in p["domains"] if d["id"] == did)


def test_empty_dir_does_not_break(tmp_path):
    p = build_ach_payload(tmp_path, make_domains())
    assert [d["id"] for d in p["domains"]] == ["learning", "sports"]
    assert p["pending_count"] == 0 and p["by_year"] == []
    assert len(p["radar"]) == 3  # 旅遊 + 兩個領域
    assert all(r["value"] == 0 for r in p["radar"])
    assert _dom(p, "learning")["latest"] is None


def test_domain_summary_and_grid(tmp_path):
    _setup(tmp_path, [row("1", level="3", item="A", title="t1"), row("2", level="1", item="B", date="2023-02", title="t2")], None)
    p = build_ach_payload(tmp_path, make_domains())
    d = _dom(p, "learning")
    assert d["xp"] == 4 and d["unlocked"] == 2 and d["level"] == 3
    assert d["latest"]["title"] == "t1"
    cells = {c["item"]: c for c in d["sets"][0]["cells"]}
    assert cells["A"]["unlocked"] and cells["B"]["unlocked"] and not cells["C"]["unlocked"]
    assert cells["C"]["item"] == "C"  # 沒解鎖的格子也有名字
    assert [c["title"] for c in d["cards"]] == ["t2", "t1"]  # 由舊到新
    card = d["cards"][0]
    assert {"domain", "item", "title", "level", "date", "memory", "source", "together", "pending"} <= set(card)
    assert card["pending"] is False
    assert d["level_defs"]["3"] == "L3"


def test_radar_seven_axes_with_travel(tmp_path):
    _setup(tmp_path, [row("1", level="5", item="A")], None)
    p = build_ach_payload(tmp_path, make_domains(top_n=5), travel=[5, 4, 3, 0, 0, 0])
    axes = {r["id"]: r["value"] for r in p["radar"]}
    assert axes["travel"] == 12 / 5 and axes["learning"] == 1.0 and axes["sports"] == 0
    assert p["radar"][0]["id"] == "travel" and p["travel"]["name"] == "旅遊"
    # 旅遊軸只取前 top_n
    p2 = build_ach_payload(tmp_path, make_domains(top_n=2), travel=[1, 5, 3])
    assert {r["id"]: r["value"] for r in p2["radar"]}["travel"] == 4.0


def test_suppressed_counts_but_not_shown(tmp_path):
    _setup(tmp_path, [row("1", level="4", item="A", date="2020-01", title="t1"), row("2", level="2", item="B", date="2024-01", title="t2")],
           None, suppress=[{"domain": "learning", "item": "A"}])
    p = build_ach_payload(tmp_path, make_domains())
    d = _dom(p, "learning")
    assert d["xp"] == 6 and d["unlocked"] == 2
    assert [c["title"] for c in d["cards"]] == ["t2"]
    assert d["latest"]["title"] == "t2"
    assert [y["year"] for y in p["by_year"]] == ["2024"]
    assert {r["id"]: r["value"] for r in p["radar"]}["learning"] == 6 / 5


def test_by_year_across_domains(tmp_path):
    _setup(tmp_path, [row("1", date="2022-03"), row("2", domain="sports", item="x", date="2022-09"),
                      row("3", date="2023")], None)
    p = build_ach_payload(tmp_path, make_domains())
    assert [(y["year"], len(y["cards"])) for y in p["by_year"]] == [("2022", 2), ("2023", 1)]


def test_include_pending_filter_rules(tmp_path):
    prows = [
        _prow("P1", level="3", decision="y"),                  # 收
        _prow("P2", level="2", suggest="y"),                   # 建議收
        _prow("P3", level="2", suggest=""),                    # 沒建議也沒否決 -> 收
        _prow("P4", level="2", suggest="n"),                   # 建議不收
        _prow("P5", level="2", decision="n", suggest="y"),     # 使用者否決
        _prow("P6", level="", suggest="y"),                    # level 空白
        _prow("P7", level="4", decision="y", suggest="n"),     # decision y 蓋過 suggest n
        _prow("P8", level="2", domain="nope"),                 # 領域不存在，略過
    ]
    _setup(tmp_path, [], prows)
    off = build_ach_payload(tmp_path, make_domains())
    assert off["pending_count"] == 0 and _dom(off, "learning")["cards"] == []
    on = build_ach_payload(tmp_path, make_domains(), include_pending=True)
    ids = sorted(c["id"] for c in _dom(on, "learning")["cards"])
    assert ids == ["P1", "P2", "P3", "P7"] and on["pending_count"] == 4
    assert all(c["pending"] for c in _dom(on, "learning")["cards"])
    assert _dom(on, "learning")["xp"] == 4  # 同項目 A 取最高級


def test_pending_without_suggest_column_and_already_in_main(tmp_path):
    old_header = ",".join(f for f in PENDING_FIELDS if f not in ("suggest", "reason")) + "\n"
    d = dict.fromkeys(PENDING_FIELDS, "")
    d.update(achievement_id="P1", domain="learning", item="A", title="舊表", level="2", date="2024", confirmed="false")
    line = ",".join(d[f] for f in PENDING_FIELDS if f not in ("suggest", "reason")) + "\n"
    dup = dict(d, achievement_id="1")
    dupl = ",".join(dup[f] for f in PENDING_FIELDS if f not in ("suggest", "reason")) + "\n"
    _setup(tmp_path, [row("1", level="1")], [line, dupl], pend_header=old_header)
    p = build_ach_payload(tmp_path, make_domains(), include_pending=True)
    assert p["pending_count"] == 1  # 已在主檔的不重複算


def test_pending_suppressed_not_in_wall(tmp_path):
    _setup(tmp_path, [], [_prow("P1", level="3", decision="y")], suppress=[{"domain": "learning", "item": "A"}])
    p = build_ach_payload(tmp_path, make_domains(), include_pending=True)
    assert _dom(p, "learning")["cards"] == [] and _dom(p, "learning")["xp"] == 3


def _lifemap_payload(**kw):
    return build_payload(paths.EXAMPLE_DIR, paths.REFERENCE, paths.config("levels"), paths.config("sets"),
                         paths.config("scoring"), **kw)


def test_build_payload_without_ach_unchanged():
    assert "ach" not in _lifemap_payload()


def test_build_payload_with_ach_and_render():
    from lifemap.achievements import load_domains_for
    p = _lifemap_payload(ach_domains=load_domains_for(paths.EXAMPLE_DIR))
    assert len(p["ach"]["radar"]) == 7
    assert p["ach"]["travel"]["xp"] > 0
    html = render_html(p, paths.REFERENCE, paths.VENDOR)
    assert "/*__" not in html and 'src="http' not in html and "https://cdn" not in html
    assert html.count("<script>") == html.count("</script>") == 3
    m = re.search(r"const DATA = (\{.*?\});\n", html, re.S)
    assert "ach" in json.loads(m.group(1))


def test_unconfirmed_main_rows_only_in_preview(tmp_path):
    _setup(tmp_path, [row("1", level="3", confirmed="false", title="未確認")], None)
    off = build_ach_payload(tmp_path, make_domains())
    assert _dom(off, "learning")["cards"] == [] and _dom(off, "learning")["xp"] == 0
    on = build_ach_payload(tmp_path, make_domains(), include_pending=True)
    assert [c["pending"] for c in _dom(on, "learning")["cards"]] == [True]


def test_template_year_order_dated_newest_first_undated_last():
    import re
    import shutil
    import subprocess
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "lifemap" / "template.html").read_text(encoding="utf-8")
    m = re.search(r"function achYearsNewestFirst\(list\) \{.*?\n\}\n", html, re.S)
    assert m and "achYearsNewestFirst(ACH.by_year)" in html
    node = shutil.which("node")
    if not node:
        return
    js = m.group(0) + "console.log(JSON.stringify(achYearsNewestFirst(" \
        '[{year:"2022"},{year:"未記日期"},{year:"2024"},{year:"2023"}]).map(y=>y.year)));'
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8").stdout
    assert json.loads(out) == ["2024", "2023", "2022", "未記日期"]
