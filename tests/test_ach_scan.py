r"""成就掃描 check_achievements.py／lifemap.ach_scan：頻率、新候選偵測、唯讀。全部用假資料（暫存資料夾）。"""
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta

from _ach import ROOT
from lifemap.ach_scan import STATE, find_new, is_due, last_scan, record_scan
from lifemap.pending import read_rows

EX = ROOT / "private.example"


def mk(tmp_path):
    """範例資料複製到暫存資料夾（pending 與 achievements 先清空，掃描一定有新候選）。"""
    d = tmp_path / "data"
    shutil.copytree(EX, d)
    for f in ("pending_achievements.csv",):
        (d / f).unlink(missing_ok=True)
    return d


def run(d, *args):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_achievements.py"),
                           "--data-dir", str(d), *args], capture_output=True, text=True, encoding="utf-8")


def snap(d):
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def test_is_due_logic(tmp_path):
    t = date(2026, 10, 30)
    assert is_due(tmp_path, t) == (True, None)
    record_scan(tmp_path, t - timedelta(days=29))
    assert is_due(tmp_path, t)[0] is False
    record_scan(tmp_path, t - timedelta(days=30))
    assert is_due(tmp_path, t)[0] is True
    (tmp_path / STATE).write_text("壞掉", encoding="utf-8")
    assert last_scan(tmp_path) is None


def test_new_candidates_exit_10_and_nothing_written(tmp_path):
    d = mk(tmp_path)
    before = snap(d)
    r = run(d)
    assert r.returncode == 10, r.stdout + r.stderr
    assert "筆新候選" in r.stdout and r.stdout.count("\n") == 1          # 一行
    assert snap(d) == before                                           # 有新候選：不寫任何檔（也不記掃描日）


def test_no_new_records_date_then_skips(tmp_path):
    d = mk(tmp_path)
    new, total = find_new(d, ROOT / "config")
    assert new and total
    # 模擬 import --write：把這些候選放進確認表，之後就沒有新的了
    from lifemap.ach_pending import merge_pending
    from lifemap.ach_scan import gather
    cfg_rows = gather(d, ROOT / "config")
    merge_pending(d / "pending_achievements.csv", cfg_rows, set())
    r = run(d)
    assert r.returncode == 0 and "沒有新的" in r.stdout, r.stdout + r.stderr
    assert json.loads((d / STATE).read_text(encoding="utf-8"))["last_scan"] == date.today().isoformat()
    r2 = run(d)
    assert r2.returncode == 0 and "未滿 30 天，跳過" in r2.stdout
    r3 = run(d, "--force")
    assert "跳過" not in r3.stdout


def test_new_item_after_pending_exists_is_detected(tmp_path):
    d = mk(tmp_path)
    from lifemap.ach_pending import merge_pending
    from lifemap.ach_scan import gather
    rows = gather(d, ROOT / "config")
    merge_pending(d / "pending_achievements.csv", rows[1:], set())      # 少一筆
    new, _ = find_new(d, ROOT / "config")
    assert [r["achievement_id"] for r in new] == [rows[0]["achievement_id"]]
    assert len(read_rows(d / "pending_achievements.csv")) == len(rows) - 1    # find_new 不改正本


def test_already_accepted_not_new(tmp_path):
    d = mk(tmp_path)
    from lifemap.ach_scan import gather
    ids = {r["achievement_id"] for r in gather(d, ROOT / "config")}
    ach_ids = {r["achievement_id"] for r in read_rows(d / "achievements.csv")}
    new, _ = find_new(d, ROOT / "config")
    assert not ({r["achievement_id"] for r in new} & ach_ids) and ids


def test_missing_config_exit_1(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 1 and "找不到" in r.stdout


def test_example_mode_does_not_record(tmp_path):
    before = snap(EX)
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_achievements.py"),
                        "--example", "--force"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode in (0, 10) and snap(EX) == before
