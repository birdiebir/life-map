r"""擴充的成就候選來源（來源擴充）：檔案索引、相簿事件、JSONL 事件。

三個來源都是通用的（別人的資料夾、相簿目錄、信件萃取結果也能用），路徑與規則全部在
private\achievement_sources.json，不寫死在程式裡。和 ach_sources.py 的其他來源一樣：
  - candidates() -> list[dict]，鍵是 ACH_FIELDS ＋ evidence，confirmed 一律 false、level 留空（等級要 Opus 判）
  - 來源層級的去雜訊用 drop_any／require_any（regex），領域與項目用 domain_rules（見 ach_sources.text_gate／route）

社群平台（Facebook／Instagram）的來源把 origin 設成 fb_／ig_ 開頭（例如 fb_group_admin）：
ach_pending.never_auto 會認得，把握度強制「低」、auto_decide 永遠不自動決定。
"""
from __future__ import annotations

import csv
import glob as globmod
import json
import re
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

from .ach_sources import _candidate, _clean, _dedupe, _title_from, date_ok, normalize_date, route, text_gate

_FB_DATE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*,\s*((?:19|20)\d{2})")
_ISO_DATE = re.compile(r"^\s*((?:19|20)\d{2})-(\d{2})-(\d{2})")


def parse_event_date(text: str) -> str:
    """ISO（2026-10-13T08:26:45）、Facebook 匯出的「11 月 25, 2017 12:24:57 上午」、其他常見寫法 → YYYY[-MM[-DD]]；認不得回傳空字串。"""
    t = text or ""
    m = _ISO_DATE.match(t)
    if m:
        return normalize_date("-".join(m.groups()))
    m = _FB_DATE.search(t)
    if m:
        return normalize_date(f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
    return normalize_date(t)


def _mtime_date(path: Path) -> str:
    try:
        return date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return ""


class FileIndexSource:
    r"""檔名清單／資料夾 INDEX.md → 候選（作品、獎項、研究報告、證書檔案這類「有檔案為證」的成就）。

    兩種模式：
    - index：讀 db-index 產生的 INDEX.md（`## 區段` 標題底下的表格，欄位 檔案｜修改｜這是什麼），一份文件一筆；
      section_contains 只收標題含其中一個字串的區段（例如「作品集與獎項」）；標題＝摘要（去掉日期片段，最多 60 字）。
    - glob：沒有 INDEX.md 的資料夾，直接列檔名（glob 可用 **；標題＝檔名去副檔名）。
    日期：摘要或檔名裡的日期；找不到時 date_fallback 設 "mtime" 才用檔案修改日（預設不用，批次複製的修改日不代表事件日期）。
    其他設定：exts（副檔名白名單）、exclude_files（regex，比對檔名）、origin（預設 file_index）、drop_any／require_any／domain_rules。
    出處＝INDEX.md 名稱#區段/檔名（ID 不含行號）。evidence 只有檔名與摘要，不讀檔案內容。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "file_index")
        self.skipped: dict[str, int] = {}

    def _skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def _emit(self, out: list, title: str, date_s: str, source: str, ev: str, fname: str) -> None:
        cfg = self.cfg
        if any(re.search(p, fname) for p in cfg.get("exclude_files") or []):
            self._skip("排除的檔名")
            return
        exts = [e.lower() for e in cfg.get("exts") or []]
        if exts and Path(fname).suffix.lower() not in exts:
            self._skip("副檔名不在白名單")
            return
        text = f"{title} {fname} {ev}"
        if not text_gate(cfg, text):
            self._skip("沒過去雜訊")
            return
        routed = route(cfg, text)
        if routed is None:
            self._skip("沒對到領域規則")
            return
        out.append(_candidate({**cfg, "domain": routed[0]}, cfg.get("origin", "file_index"), title, date_s,
                              source, ev[:200], routed[1]))

    def candidates(self) -> list[dict]:
        self.skipped = {}
        return _dedupe(self._from_index() if self.cfg.get("index") else self._from_glob())

    def _from_index(self) -> list[dict]:
        cfg = self.cfg
        path = Path(cfg["index"])
        fcol, scol, mcol = cfg.get("file_col", "檔案"), cfg.get("summary_col", "這是什麼"), cfg.get("mtime_col", "修改")
        want = cfg.get("section_contains") or []
        if isinstance(want, str):
            want = [want]
        out: list[dict] = []
        section, header = "", None
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if s.startswith("#"):
                section, header = s.lstrip("#").strip(), None
                continue
            if not s.startswith("|"):
                header = None
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if header is None:
                if fcol in cells and scol in cells:
                    header = cells
                continue
            if re.fullmatch(r"[|\s:\-]+", s):
                continue
            if want and not any(w in section for w in want):
                continue
            row = dict(zip(header, cells))
            fname, summary = row.get(fcol, ""), _clean(row.get(scol, ""))
            if not fname:
                continue
            title = _title_from(summary) or Path(fname).stem[:60]
            d = normalize_date(summary) or normalize_date(fname)
            if not d and cfg.get("date_fallback") == "mtime":
                d = normalize_date(row.get(mcol, ""))
            self._emit(out, title, d, f"{path.name}#{section}/{fname}", f"{fname}｜{summary}", fname)
        return out

    def _from_glob(self) -> list[dict]:
        cfg = self.cfg
        pats = [cfg["glob"]] if cfg.get("glob") else []
        pats += list(cfg.get("globs") or [])
        root = Path(cfg["root"]) if cfg.get("root") else None
        out: list[dict] = []
        for pat in pats:
            for f in sorted(globmod.glob(pat, recursive=True)):
                p = Path(f)
                if not p.is_file() or p.name.lower() in ("desktop.ini", "index.md", "claude.md"):
                    continue
                rel = p.relative_to(root).as_posix() if root and p.is_relative_to(root) else p.name
                d = normalize_date(p.stem)
                if not d and cfg.get("date_fallback") == "mtime":
                    d = _mtime_date(p)
                title = _title_from(re.sub(r"[_]+", " ", p.stem)) or p.stem[:60]
                self._emit(out, title, d, rel, rel, p.name)
        return out


_NAME_DATE8 = re.compile(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)")
_NAME_DATE7 = re.compile(r"(?<!\d)(\d{3})(\d{2})(\d{2})(?!\d)")
_NAME_ISO = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.](\d{2})[-_.](\d{2})(?!\d)")


def _valid_ymd(y: int, m: int, d: int) -> str:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return ""


def name_date(key: str) -> str:
    r"""相簿／資料夾名稱裡的日期 → YYYY-MM-DD，沒有回傳空字串。看最後一層名稱。
    支援 2014-06-23（ISO）、20160312（西元 8 碼）、1030620（民國 7 碼：103＝2014，年份 80～130 才算）。
    照片的上傳日、修改日不是事件日期，所以名稱裡有日期就優先用它。"""
    leaf = (key or "").replace(chr(92), "/").rsplit("/", 1)[-1]
    m = _NAME_ISO.search(leaf)
    if m:
        return _valid_ymd(*map(int, m.groups()))
    m = _NAME_DATE8.search(leaf)
    if m:
        return _valid_ymd(*map(int, m.groups()))
    m = _NAME_DATE7.search(leaf)
    if m and 80 <= int(m.group(1)) <= 130:
        return _valid_ymd(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    return ""


def _album_key_ok(key: str) -> bool:
    return bool(key and key.strip())


def group_albums(cfg: dict) -> tuple[list[dict], dict[str, int]]:
    r"""照片目錄 CSV → 相簿／資料夾分組。回傳 ([{key, n, ds, de, precision, folder, ctx}], 略過計數)。

    cfg：catalog（CSV）、group_by（line_album 或 folder，預設 line_album）、min_photos（預設 5）、
    outlier_days（偏離中位數超過幾天的拍攝日當成 EXIF 亂掉，預設 60）、context_csv（資料夾背景表，照片沒日期時
    用 date_range_推定 補）。日期優先序：相簿／資料夾名稱裡的日期（name_date）→ 照片拍攝日（只取 date_precision 為 day／month 的列，
    有 day 精度的優先；日期等於雲端修改日的非 EXIF 列視為上傳時間戳、不用）→ 資料夾背景表推定。
    不輸出任何照片檔名或路徑，只輸出分組名稱與張數、日期範圍。
    """
    key_col = cfg.get("group_by", "line_album")
    if key_col == "folder":
        key_col = "folder"
    min_n = int(cfg.get("min_photos", 5))
    out_days = int(cfg.get("outlier_days", 60))
    ctx: dict[str, dict] = {}
    if cfg.get("context_csv") and Path(cfg["context_csv"]).exists():
        with Path(cfg["context_csv"]).open(encoding="utf-8-sig", newline="") as fh:
            ctx = {r.get("folder", ""): r for r in csv.DictReader(fh)}
    groups: dict[str, dict] = {}
    with Path(cfg["catalog"]).open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            key = (r.get(key_col) or "").strip()
            if not _album_key_ok(key):
                continue
            g = groups.setdefault(key, {"n": 0, "day": [], "month": [], "folders": Counter()})
            g["n"] += 1
            g["folders"][r.get("folder", "")] += 1
            prec, dt = r.get("date_precision", ""), (r.get("date_taken") or "")[:10]
            if dt and dt == (r.get("drive_modified") or "")[:10] and r.get("date_source") != "EXIF":
                prec = ""                                    # 日期等於雲端修改日（檔名裡是上傳時間戳）：不是拍攝日，不用
            try:
                if prec == "day":
                    g["day"].append(date.fromisoformat(dt))
                elif prec == "month":
                    g["month"].append(date.fromisoformat(dt[:7] + "-01"))
            except ValueError:
                pass
    skipped: dict[str, int] = {}
    out = []
    for key, g in groups.items():
        if g["n"] < min_n:
            skipped["張數太少"] = skipped.get("張數太少", 0) + 1
            continue
        ds_list, precision = (g["day"], "day") if g["day"] else (g["month"], "month")
        folder = g["folders"].most_common(1)[0][0]
        row_ctx = ctx.get(key if cfg.get("group_by") == "folder" else folder, {})
        nd = name_date(key)
        if nd:                                               # 相簿／資料夾名稱裡的日期優先於照片拍攝日
            ds, de, precision = nd, nd, "name"
        elif ds_list:
            med = statistics.median(d.toordinal() for d in ds_list)
            kept = [d for d in ds_list if abs(d.toordinal() - med) <= out_days] or ds_list
            lo, hi = min(kept), max(kept)
            ds = lo.isoformat() if precision == "day" else lo.isoformat()[:7]
            de = hi.isoformat() if precision == "day" else hi.isoformat()[:7]
        else:
            ds = normalize_date(row_ctx.get("date_range_推定", ""))
            de, precision = ds, "context" if ds else "none"
        out.append({"key": key, "n": g["n"], "ds": ds, "de": de, "precision": precision, "folder": folder,
                    "ctx": row_ctx})
    return out, skipped


def match_rule(rules: list[dict], key: str) -> dict | None:
    for r in rules:
        if re.search(r["match"], key):
            return r
    return None


class PhotoAlbumSource:
    r"""相簿事件：照片目錄 CSV（照片目錄.csv：line_album、folder、date_taken…）→ 一個相簿（或資料夾）一筆候選。

    相簿名＝事件名，日期取相簿內照片拍攝日的範圍（起日當 date，範圍寫進 evidence）。月份相簿（CityA-Mar2024
    這類整理用的）、「All」這類不是事件，所以只收 rules 命中的：rules＝[{"match": regex（比對相簿名或資料夾路徑）,
    "domain", "item", "title": 可省略（預設相簿名）, "together": 可省略}]，先中先贏，沒命中的略過（計入 skipped）。
    設定：catalog、group_by（line_album／folder）、min_photos、outlier_days、context_csv、origin（預設 album）。
    旅遊足跡不走這裡（走 import_event_places.py 的 album_places）。evidence 不含照片檔名或座標。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "photo_albums")
        self.skipped: dict[str, int] = {}

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        groups, self.skipped = group_albums(cfg)
        rules = cfg.get("rules") or []
        out = []
        for g in groups:
            rule = match_rule(rules, g["key"])
            if rule is None:
                self.skipped["沒對到規則"] = self.skipped.get("沒對到規則", 0) + 1
                continue
            dom = rule.get("domain", cfg["domain"])
            title = _clean(rule.get("title") or re.sub(r"^\d{4}-\d{2}-\d{2}[_ ]", "", g["key"].rsplit("/", 1)[-1]))[:60]
            rng = f"{g['ds']}～{g['de']}" if g["ds"] and g["de"] != g["ds"] else g["ds"]
            ev = f"{g['n']} 張照片；日期 {rng or '不明'}（{ {'day': '日', 'month': '月', 'name': '相簿名稱', 'context': '資料夾背景表推定', 'none': '無'}[g['precision']] }精度）；{'資料夾' if cfg.get('group_by') == 'folder' else '相簿'}：{g['key']}"
            sit = (g["ctx"].get("situation") or "").strip()
            if sit:
                ev += f"；情境：{sit}"
            c = _candidate({**cfg, "domain": dom}, cfg.get("origin", "album"), title, g["ds"],
                           f"{Path(cfg['catalog']).name}#{g['key']}", ev[:200], rule.get("item") or cfg.get("item", "未分類"))
            if rule.get("together"):
                c["together"] = "true"
            out.append(c)
        return _dedupe(out)


class JsonlEventsSource:
    r"""JSONL 記錄 → 候選（Gmail 萃取結果、Facebook 匯出整理後的社團管理紀錄等，一行一筆 JSON）。

    設定：files／glob、date_field（日期欄位；ISO 或「11 月 25, 2017 …」格式）、text_field（標題來源欄位，預設 subject）、
    include（regex 清單，至少命中一個才收）、exclude（regex 清單，命中就丟）、title_regex（第一個群組當標題，沒命中就用整段文字）、
    title_prefix、origin（必填；Facebook／Instagram 來源請用 fb_／ig_ 開頭，會被強制低把握度、不自動決定）、
    evidence_fields（evidence 附上的欄位，例如 sender_domain）、drop_any／require_any／domain_rules。
    同一天同標題只留一筆。出處＝檔名（ID 不含行號）。不抄內文，只用主旨／標題欄位。
    """

    def __init__(self, cfg: dict):
        if not cfg.get("origin"):
            raise ValueError("jsonl_events 來源要設定 origin（社群平台用 fb_／ig_ 開頭）")
        self.cfg = cfg
        self.name = cfg.get("name", "jsonl_events")
        self.skipped: dict[str, int] = {}

    def _skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def _files(self) -> list[Path]:
        cfg = self.cfg
        paths = [Path(p) for p in cfg.get("files", [])]
        if cfg.get("glob"):
            paths += [Path(p) for p in sorted(globmod.glob(cfg["glob"]))]
        return [p for p in paths if p.exists()]

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        self.skipped = {}
        tf, df = cfg.get("text_field", "subject"), cfg["date_field"]
        inc, exc = cfg.get("include") or [], cfg.get("exclude") or []
        out = []
        for path in self._files():
            with path.open(encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        self._skip("JSON 壞行")
                        continue
                    text = str(rec.get(tf) or "")
                    if inc and not any(re.search(p, text) for p in inc):
                        continue
                    if any(re.search(p, text) for p in exc):
                        self._skip("exclude 命中")
                        continue
                    d = parse_event_date(str(rec.get(df) or ""))
                    if not d:
                        self._skip("日期無法辨識")
                        continue
                    m = re.search(cfg["title_regex"], text) if cfg.get("title_regex") else None
                    title = _clean((m.group(1) if m and m.groups() else text))[:60].strip()
                    title = (cfg.get("title_prefix", "") + title)[:60]
                    if not title:
                        continue
                    gate_text = f"{title} {text}"
                    if not text_gate(cfg, gate_text) or not date_ok(cfg, d):
                        continue
                    routed = route(cfg, gate_text)
                    if routed is None:
                        continue
                    extra = "｜".join(str(rec.get(k)) for k in cfg.get("evidence_fields") or [] if rec.get(k))
                    ev = f"{d}｜{text}" + (f"｜{extra}" if extra else "")
                    out.append(_candidate({**cfg, "domain": routed[0]}, cfg["origin"], title, d, path.name,
                                          ev[:200], routed[1]))
        return _dedupe(out)


EXT_TYPES = {"file_index": FileIndexSource, "photo_albums": PhotoAlbumSource, "jsonl_events": JsonlEventsSource}
