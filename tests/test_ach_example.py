"""Task 5：範例假資料可被讀取，import_achievements.py --dry-run 跑得通且不寫檔。"""
import subprocess
import sys

from _ach import ROOT, real_domains
from lifemap.achievements import load_achievements, load_suppress_rules

EX = ROOT / "private.example"


def test_example_achievements_cover_all_domains_and_cases():
    d = real_domains()
    achs = load_achievements(EX / "achievements.csv", d)
    assert {a.domain for a in achs} == set(d.by_id)
    assert any(a.suppressed for a in achs) and any(a.together for a in achs) and any(not a.confirmed for a in achs)
    assert load_suppress_rules(EX / "achievement_suppress.json")


def test_dry_run_with_example_writes_nothing():
    before = sorted(p.name for p in EX.iterdir())
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "import_achievements.py"),
                        "--dry-run", "--example"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "範例職涯里程碑表：2 筆候選" in r.stdout and "範例學習筆記：3 筆候選" in r.stdout
    assert "範例訓練筆記：2 筆候選" in r.stdout and "範例家族時間軸：3 筆候選" in r.stdout
    assert sorted(p.name for p in EX.iterdir()) == before


def test_write_with_example_refused():
    before = sorted(p.name for p in EX.iterdir())
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "import_achievements.py"),
                        "--write", "--example"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode != 0
    assert sorted(p.name for p in EX.iterdir()) == before


def test_example_rules_and_sets_load():
    from lifemap.ach_rules import load_rules
    from lifemap.achievements import load_domains_for
    r = load_rules(ROOT / "config" / "ach_rules.json", EX / "achievement_rules.json")
    assert r["noise"]["signals"][0] == "範例關鍵字" and r["item_rules"][0]["item"] == "碩士"
    d = load_domains_for(EX)
    assert {s.id for s in d.by_id["learning"].sets} >= {"learning_cert", "learning_example"}
