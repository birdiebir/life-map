import os
import subprocess

import paths
from lifemap import kbsync, newdata
from lifemap.build import build_payload
from lifemap.reference import load_places

CFG = {
    "start_marker": "<!-- a:start -->", "end_marker": "<!-- a:end -->",
    "insert_before_heading": "## 已踩點", "heading": "## 進度",
    "set_ids": ["un_countries", "tw_counties"],
}


def _payload():
    places = load_places(paths.REFERENCE)
    p = build_payload(paths.EXAMPLE_DIR, paths.REFERENCE, paths.config("levels"), paths.config("sets"),
                      paths.config("scoring"), places=places)
    return p, {k: v.name for k, v in places.items()}


def test_render_block_has_table_and_countries():
    p, names = _payload()
    b = kbsync.render_block(p, names, CFG)
    assert "| 項目 | 去過 | 總數 |" in b and "去過的國家／地區：" in b
    assert "日本" in b


def test_apply_inserts_before_heading_and_is_idempotent():
    p, names = _payload()
    b = kbsync.render_block(p, names, CFG)
    old = "# 標題\n\n手寫內容\n\n## 已踩點\n\n表格\n"
    new = kbsync.apply_block(old, b, CFG)
    assert new.index("<!-- a:start -->") < new.index("## 已踩點")
    assert "手寫內容" in new and new.endswith("表格\n")
    assert kbsync.apply_block(new, b, CFG) == new
    assert kbsync.current_block(new, CFG) == b


def test_update_only_touches_block():
    old = "前\n<!-- a:start -->\n舊\n<!-- a:end -->\n後\n"
    new = kbsync.apply_block(old, "新", CFG)
    assert new == "前\n<!-- a:start -->\n新\n<!-- a:end -->\n後\n"
    assert kbsync.changed_count(kbsync.diff_lines(old, new)) == 2


def test_shrinks_detects_removal_not_addition():
    old = "| 國家 | 5 | 193 |\n\n去過的國家／地區：日本、南韓"
    assert kbsync.shrinks(old, "| 國家 | 6 | 193 |\n\n去過的國家／地區：日本、南韓、泰國") == []
    s = kbsync.shrinks(old, "| 國家 | 4 | 193 |\n\n去過的國家／地區：日本")
    assert len(s) == 2
    assert kbsync.shrinks(None, "x") == []


def test_git_commit_only_adds_that_note(tmp_path):
    def g(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True,
                              encoding="utf-8").stdout
    g("init")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "t")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    g("add", "b.md")  # b 已暫存，不該被一起 commit
    kbsync.git_commit_note(tmp_path, "a.md", "msg", "Co-Authored-By: X <x@example.com>")
    assert g("show", "--name-only", "--format=%B", "HEAD").split() .count("a.md") == 1
    assert "b.md" not in g("show", "--name-only", "--format=", "HEAD")
    assert "Co-Authored-By: X" in g("log", "-1", "--format=%B")


def _touch(path, t):
    path.write_text("x", encoding="utf-8")
    os.utime(path, (t, t))


def test_find_new_by_mtime_and_state(tmp_path):
    watch = tmp_path / "dl"
    watch.mkdir()
    old_zip = watch / "takeout-1.zip"
    _touch(old_zip, 1000)
    (tmp_path / "sources.json").write_text('{"watch_dirs": ["%s"]}' % str(watch).replace("\\", "\\\\"), encoding="utf-8")
    pending = tmp_path / "pending.csv"
    _touch(pending, 2000)
    # 沒有匯入紀錄：以 pending.csv 時間為基準，舊 zip 不算新
    assert newdata.find_new(tmp_path)[0] == []
    new_zip = watch / "takeout-2.zip"
    _touch(new_zip, 3000)
    assert newdata.find_new(tmp_path)[0] == [new_zip]
    # 匯入後記下狀態，就沒有新檔；zip 再更新才又算新
    newdata.record_import(tmp_path, [old_zip, new_zip])
    assert newdata.find_new(tmp_path)[0] == []
    os.utime(new_zip, (9999999999, 9999999999))
    assert newdata.find_new(tmp_path)[0] == [new_zip]


def test_find_new_without_sources(tmp_path):
    assert newdata.find_new(tmp_path)[0] == []
