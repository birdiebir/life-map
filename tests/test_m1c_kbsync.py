"""M1c-B：kb_sync 設定分層（config 通用預設、private 個人值蓋過）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifemap import kbsync
from lifemap.data import DataError

ROOT = Path(__file__).resolve().parent.parent


def _w(p: Path, d: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_private_overrides_config(tmp_path):
    _w(tmp_path / "c" / "kb_sync.json", {"heading": "H", "commit_message": "通用", "max_changed_lines": 40})
    _w(tmp_path / "p" / "kb_sync.json", {"kb_root": "X", "note": "a.md", "commit_message": "個人"})
    cfg = kbsync.load_config(tmp_path / "c", tmp_path / "p")
    assert cfg["commit_message"] == "個人"
    assert cfg["heading"] == "H" and cfg["kb_root"] == "X" and cfg["note"] == "a.md"


@pytest.mark.parametrize("missing", ["kb_root", "note"])
def test_missing_required_key_raises_with_hint(tmp_path, missing):
    _w(tmp_path / "c" / "kb_sync.json", {"heading": "H"})
    priv = {"kb_root": "X", "note": "a.md"}
    priv.pop(missing)
    _w(tmp_path / "p" / "kb_sync.json", priv)
    with pytest.raises(DataError) as e:
        kbsync.load_config(tmp_path / "c", tmp_path / "p")
    assert missing in str(e.value) and "private.example" in str(e.value)


def test_missing_private_file_raises(tmp_path):
    _w(tmp_path / "c" / "kb_sync.json", {"heading": "H"})
    with pytest.raises(DataError) as e:
        kbsync.load_config(tmp_path / "c", tmp_path / "nope")
    assert "private.example" in str(e.value)


def test_broken_private_json_raises_dataerror_with_filename(tmp_path):
    _w(tmp_path / "c" / "kb_sync.json", {"heading": "H"})
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "kb_sync.json").write_text("{壞掉", encoding="utf-8")
    with pytest.raises(DataError) as e:
        kbsync.load_config(tmp_path / "c", tmp_path / "p")
    assert "kb_sync.json" in str(e.value)


def test_missing_or_broken_config_raises_dataerror(tmp_path):
    with pytest.raises(DataError) as e:
        kbsync.load_config(tmp_path / "nope", tmp_path / "p")
    assert "kb_sync.json" in str(e.value)
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "kb_sync.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(DataError):
        kbsync.load_config(tmp_path / "c", tmp_path / "p")


def test_config_has_no_personal_paths():
    cfg = json.loads((ROOT / "config" / "kb_sync.json").read_text(encoding="utf-8"))
    for k in ("kb_root", "note", "insert_before_heading"):
        assert k not in cfg
    assert "Knowledge base" not in json.dumps(cfg, ensure_ascii=False)


def test_example_loads_with_config():
    cfg = kbsync.load_config(ROOT / "config", ROOT / "private.example")
    assert cfg["kb_root"] and cfg["note"] and cfg["set_ids"]
