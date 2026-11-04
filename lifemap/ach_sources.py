r"""成就候選的來源（可替換）。

每個來源實作 candidates() -> list[dict]，dict 的鍵是 ACH_FIELDS ＋ evidence，confirmed 一律 false、level 預設留空
（判斷等級要 Opus，不在這裡做）。來源路徑與欄位對應由 private\achievement_sources.json 設定，不寫死在程式。

候選 ID＝"A-" + sha1(領域｜來源類型｜出處（去掉行號）｜標題｜日期) 前 10 碼：重跑固定，筆記多加一行也不會變。
"""
from __future__ import annotations

import csv
import glob as globmod
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from .achievements import ACH_FIELDS, _bounds
from .data import DATE_RE

_LINE_SUFFIX = re.compile(r":\d+$")
_DATE_FIND = re.compile(
    r"(?<!\d)((?:19|20)\d{2})"
    r"(?:\s*[-/.]\s*(\d{1,2})(?:\s*[-/.]\s*(\d{1,2}))?"
    r"|\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?)?(?!\d)")


def candidate_id(domain: str, origin: str, source: str, title: str, date: str = "") -> str:
    raw = "|".join([domain, origin, _LINE_SUFFIX.sub("", source), title, date])
    return "A-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def normalize_date(text: str) -> str:
    """'2021/6/7'、'2022 年 3 月'、'2021-09-06' → 標準格式；認不得就回傳空字串。"""
    m = _DATE_FIND.search(text or "")
    if not m:
        return ""
    y, m1, d1, m2, d2 = m.groups()
    month, day = m1 or m2, d1 or d2
    out = y
    if month:
        if not 1 <= int(month) <= 12:
            return y
        out += f"-{int(month):02d}"
        if day:
            if not 1 <= int(day) <= 31:
                return out
            out += f"-{int(day):02d}"
    return out if DATE_RE.match(out) else ""


def _candidate(cfg: dict, origin: str, title: str, date: str, source: str, evidence: str, item: str) -> dict:
    row = {f: "" for f in ACH_FIELDS}
    row.update(domain=cfg["domain"], item=item, title=title, level=str(cfg.get("level", "")), date=date,
               together="false", source=source, origin=origin, confirmed="false", suppressed="false",
               evidence=evidence)
    row["achievement_id"] = candidate_id(cfg["domain"], origin, source, title, date)
    return row


def text_gate(cfg: dict, text: str) -> bool:
    """來源層級的雜訊閘門：drop_any（regex，任一命中就丟）、require_any（regex，至少命中一個才收）；沒設定就放行。
    比全域去雜訊（ach_rules.json，只對 kb_note 生效）更細：每個來源自己決定什麼算里程碑。"""
    if any(re.search(p, text) for p in cfg.get("drop_any") or []):
        return False
    req = cfg.get("require_any") or []
    return not req or any(re.search(p, text, re.IGNORECASE) for p in req)


def date_ok(cfg: dict, date_s: str) -> bool:
    """date_max（"YYYY-MM-DD" 或 "today"）：比這個日期晚的候選丟掉（未來的計畫、期限不是成就）。沒設定或沒日期就放行。"""
    mx = cfg.get("date_max")
    if not mx or not date_s:
        return True
    from datetime import date as _d
    cut = _d.today().isoformat() if mx == "today" else str(mx)
    return date_s[:10] <= cut[:len(date_s[:10])] if len(date_s) < 10 else date_s <= cut


def route(cfg: dict, text: str) -> tuple[str, str] | None:
    """依 domain_rules（[{"match": regex, "domain": 可省略, "item": 可省略, "drop": 可省略}]，先中先贏）決定領域與項目；
    沒有規則或沒命中就用來源的 domain／item；drop_unmatched=true 時沒命中的丟掉；命中 drop=true 的丟掉。回傳 None＝丟。"""
    rules = cfg.get("domain_rules") or []
    for r in rules:
        if re.search(r["match"], text):
            if r.get("drop"):
                return None
            return r.get("domain", cfg["domain"]), r.get("item") or cfg.get("item", "未分類")
    if rules and cfg.get("drop_unmatched"):
        return None
    return cfg["domain"], cfg.get("item", "未分類")


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        if r["achievement_id"] not in seen:
            seen.add(r["achievement_id"])
            out.append(r)
    return out


def _norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", t or "").lower()


def dedupe_across(rows: list[dict]) -> list[dict]:
    """跨來源去重複：正規化標題（去空白、標點、大小寫）＋日期相同視為同一筆，保留先出現的；
    但 origin=trip（旅程表）的優先保留，不會被同標題同日期的其他來源吃掉。"""
    trip_keys = {(_norm_title(r["title"]), r.get("date", "")) for r in rows if r.get("origin") == "trip"}
    seen, out = set(), []
    for r in rows:
        key = (_norm_title(r["title"]), r.get("date", ""))
        if r.get("origin") != "trip" and key in trip_keys:
            continue
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def drop_covered_by_main(rows: list[dict], main_rows: list[dict]) -> tuple[list[dict], int]:
    """主檔（achievements.csv）已有同領域同項目、等級不低於候選的，就不產生候選（例如健身紀錄換出處字串後 ID 變了，
    但等級沒有升）。只看有填等級的候選與已確認的主檔列；候選沒等級的（要 Opus 判）不動。回傳 (留下的候選, 被擋筆數)。"""
    best: dict[tuple[str, str], int] = {}
    for m in main_rows:
        if str(m.get("confirmed", "true")).strip().lower() in ("false", "0", "no", "n"):
            continue
        lv = str(m.get("level", "")).strip()
        if lv.isdigit():
            k = (m.get("domain", ""), m.get("item", ""))
            best[k] = max(best.get(k, -1), int(lv))
    out, n = [], 0
    for r in rows:
        lv = str(r.get("level", "")).strip()
        if lv.isdigit() and best.get((r.get("domain", ""), r.get("item", "")), -1) >= int(lv):
            n += 1
            continue
        out.append(r)
    return out, n


class CsvSource:
    """通用 CSV：columns 對應 title／date／source（必要 title），filter 是 {欄位: 值或值清單}。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "csv")

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        cols = cfg["columns"]
        flt = {k: (v if isinstance(v, list) else [v]) for k, v in cfg.get("filter", {}).items()}
        out = []
        with Path(cfg["path"]).open(encoding="utf-8-sig", newline="") as fh:
            for n, r in enumerate(csv.DictReader(fh), start=2):
                r = {k: (v or "").strip() for k, v in r.items() if k}
                if any(r.get(k, "") not in vals for k, vals in flt.items()):
                    continue
                title = r.get(cols["title"], "")
                if not title:
                    continue
                item = r.get(cols["item"], "") if cols.get("item") else ""
                out.append(_candidate(cfg, "csv", title, normalize_date(r.get(cols.get("date", ""), "")),
                                      r.get(cols.get("source", ""), ""), f"{Path(cfg['path']).name} 第 {n} 列",
                                      item or cfg.get("item", "未分類")))
        return _dedupe(out)


_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")


def _clean(text: str) -> str:
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    return text.strip()


def _title_from(text: str) -> str:
    """去掉日期片段與多餘標點，留下標題（最多 60 字）。"""
    t = _DATE_FIND.sub(" ", text)
    t = re.sub(r"[（(]\s*[)）]", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—:：,，;；、|·/")
    return t[:60]


class MarkdownSource:
    """KB 筆記：只抓「含日期的條列或表格列」；出處＝相對路徑:行號。files 或 glob 擇一，exclude 是檔名清單。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "markdown")

    def _files(self) -> list[Path]:
        cfg = self.cfg
        paths = [Path(p) for p in cfg.get("files", [])]
        if cfg.get("glob"):
            paths += [Path(p) for p in sorted(globmod.glob(cfg["glob"]))]
        skip = set(cfg.get("exclude", []))
        return [p for p in paths if p.name not in skip and p.exists()]

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        root = Path(cfg["root"]) if cfg.get("root") else None
        out = []
        for path in self._files():
            rel = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else path.name
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            skip = self._table_header_lines(lines)
            only = self._first_table_lines(lines) if cfg.get("first_table_only") else None
            for n, line in enumerate(lines, start=1):
                if n in skip or (only is not None and n not in only):
                    continue
                body = self._line_body(line)
                if body is None:
                    continue
                date = normalize_date(body)
                if not date:
                    continue
                title = _title_from(_clean(body) if "|" not in line else self._cell_title(line))
                if not title:
                    continue
                text = title if cfg.get("match_on") == "title" else f"{title} {line.strip()}"
                if not text_gate(cfg, text) or not date_ok(cfg, date):
                    continue
                routed = route(cfg, text)
                if routed is None:
                    continue
                out.append(_candidate({**cfg, "domain": routed[0]}, cfg.get("origin", "kb_note"), title, date,
                                      f"{rel}:{n}", line.strip()[:200], routed[1]))
        return _dedupe(out)

    @staticmethod
    def _table_header_lines(lines: list[str]) -> set[int]:
        """表格表頭列（下一行是 |---|---| 分隔線）的行號（1 起算）；表頭不是資料，不當候選。"""
        sep = re.compile(r"[|\s:\-]+")
        return {n for n, (a, b) in enumerate(zip(lines, lines[1:]), start=1)
                if a.strip().startswith("|") and b.strip().startswith("|") and "-" in b and sep.fullmatch(b.strip())}

    @staticmethod
    def _first_table_lines(lines: list[str]) -> set[int]:
        """檔案裡第一張表（連續以 | 開頭的列）的資料列行號；first_table_only 設定用。"""
        out: set[int] = set()
        started = False
        for n, line in enumerate(lines, start=1):
            if line.strip().startswith("|"):
                started = True
                out.add(n)
            elif started:
                break
        return out

    @staticmethod
    def _line_body(line: str) -> str | None:
        m = _BULLET.match(line)
        if m:
            return m.group(1)
        s = line.strip()
        if s.startswith("|") and not re.fullmatch(r"[|\s:\-]+", s):
            return s
        return None

    @staticmethod
    def _cell_title(line: str) -> str:
        for cell in (c.strip() for c in line.strip().strip("|").split("|")):
            cell = _clean(cell)
            if cell and not _DATE_FIND.fullmatch(cell) and _title_from(cell):
                return cell
        return ""


_FULL_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
_MD_DATE = re.compile(r"(?<![\d/.-])(\d{1,2})\s*[/.]\s*(\d{1,2})(?![\d/.])")


def _week_key(d: date) -> date:
    return d - timedelta(days=d.weekday())


class TrainingLogSource:
    r"""訓練紀錄表（Markdown 表格）→ 每個運動項目只產一筆候選（通用，別人的訓練表也能用）。

    設定：date_col／category_col（表頭名稱，兩欄都在的表才算訓練表）、item_map（類別文字含有鍵就歸到值，
    照設定順序先中先贏，沒對到的列忽略）、week_start（沒寫年份的 MM/DD 用它補年份：落在起始日之後、
    或起始日前 14 天內算同年，更早的月日算隔年）、min_coverage（有紀錄的週數 ÷ 期間週數，預設 0.5）。
    等級（偏保守）：有紀錄不到 3 週＝1；期間 1 年以上且涵蓋率夠＝5；3 個月以上且涵蓋率夠＝3；其他＝2。
    限制：沒寫年份的紀錄只能補到「起始日起一年內」，超過 1 年會折回第一年，所以只靠這種紀錄到不了 5 級
    （要跨年需有完整日期，或之後讓設定分段給多個起始日）。
    evidence 只寫期間與週數，不寫重量、內容、身體數字。標題固定（不含最後日期），候選 ID 才不會每週變。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "training_log")
        self.skipped: dict[str, int] = {}

    def _files(self) -> list[Path]:
        cfg = self.cfg
        paths = [Path(p) for p in cfg.get("files", [])]
        if cfg.get("glob"):
            paths += [Path(p) for p in sorted(globmod.glob(cfg["glob"]))]
        skip = set(cfg.get("exclude", []))
        return [p for p in paths if p.name not in skip and p.exists()]

    def _parse_date(self, text: str, week_start: date | None) -> date | None:
        m = _FULL_DATE.search(text)
        try:
            if m:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            m = _MD_DATE.search(text)
            if not m:
                self._skip("日期無法辨識")
                return None
            if week_start is None:
                self._skip("無年份")
                return None
            mo, dd = int(m.group(1)), int(m.group(2))
            window = week_start - timedelta(days=14)
            try:
                prev = date(week_start.year - 1, mo, dd)       # 2/29 在平年會丟 ValueError，不影響下面
                if window <= prev:
                    return prev
            except ValueError:
                pass
            d = date(week_start.year, mo, dd)
            if d < window:
                d = date(week_start.year + 1, mo, dd)
            return d
        except ValueError:
            self._skip("日期無法辨識")
            return None

    def _skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def _level(self, first: date, last: date, weeks: set) -> int:
        if len(weeks) < 3:
            return 1
        span_days = (last - first).days
        span_weeks = (_week_key(last) - _week_key(first)).days // 7 + 1
        enough = len(weeks) / span_weeks >= float(self.cfg.get("min_coverage", 0.5))
        if span_days >= 365 and enough:
            return 5
        if span_days >= 90 and enough:
            return 3
        return 2

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        date_col, cat_col, item_map = cfg["date_col"], cfg["category_col"], cfg["item_map"]
        week_start = date.fromisoformat(cfg["week_start"]) if cfg.get("week_start") else None
        self.skipped = {}
        root = Path(cfg["root"]) if cfg.get("root") else None
        dates: dict[str, list[date]] = {}
        src_of: dict[str, str] = {}
        for path in self._files():
            rel = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else path.name
            idx = None
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                s = line.strip()
                if not s.startswith("|"):
                    idx = None
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if idx is None:
                    if date_col in cells and cat_col in cells:
                        idx = (cells.index(date_col), cells.index(cat_col))
                    continue
                if re.fullmatch(r"[|\s:\-]+", s) or max(idx) >= len(cells):
                    continue
                item = next((v for k, v in item_map.items() if k in cells[idx[1]]), None)
                if item is None:
                    continue
                d = self._parse_date(cells[idx[0]], week_start)
                if d is None:
                    continue
                dates.setdefault(item, []).append(d)
                src_of.setdefault(item, f"{rel}#{item}")      # 同檔多項目：出處帶項目，M1c 才連得上換 ID 的舊列
        return self._build(dates, src_of)

    def _build(self, dates: dict[str, list[date]], src_of: dict[str, str]) -> list[dict]:
        cfg = self.cfg
        out = []
        for item, ds in dates.items():
            first, last = min(ds), max(ds)
            weeks = {_week_key(d) for d in ds}
            ev = f"期間 {first.isoformat()}～{last.isoformat()}，共 {len(weeks)} 週有紀錄"
            title = f"{item}紀錄" if item.endswith("訓練") else f"{item}訓練紀錄"   # 項目已以「訓練」結尾就不再疊一次
            c = _candidate(cfg, "training_log", title, first.isoformat(), src_of[item], ev, item)
            c["level"] = str(self._level(first, last, weeks))
            out.append(c)
        return _dedupe(out)


class RecordsJsonSource(TrainingLogSource):
    r"""紀錄中心的健身 JSON（records\fitness-sessions.json）→ 每個運動項目一筆候選。

    等級規則沿用 TrainingLogSource（期間、有紀錄週數、涵蓋率）。JSON 結構：{"items": [{"date": "YYYY-MM-DD",
    "status": "done", "archived": false, "categoryRaw": "…", "exercises": [{"sets": [{"weightKg": 數字或 null}]}]}]}。
    設定：files（JSON 路徑）、item_map（categoryRaw 含有鍵就歸到值，先中先贏）、status（預設 ["done"]）、
    infer_by_load（沒對到 item_map 時依有沒有重量判斷：有重量＝load_item，沒有＝bodyweight_item；預設關）。
    已封存（archived）、狀態不符、日期認不得的紀錄略過並計入 skipped。evidence 只寫期間與週數，不寫內容。
    """

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        item_map = cfg.get("item_map", {})
        statuses = set(cfg.get("status", ["done"]))
        by_load = bool(cfg.get("infer_by_load", False))
        load_item = cfg.get("load_item", "重訓")
        body_item = cfg.get("bodyweight_item", "徒手訓練")
        self.skipped = {}
        root = Path(cfg["root"]) if cfg.get("root") else None
        dates: dict[str, list[date]] = {}
        src_of: dict[str, str] = {}
        for path in self._files():
            rel = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else path.name
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            for rec in data.get("items", []) if isinstance(data, dict) else []:
                if rec.get("archived") or rec.get("status") not in statuses:
                    self._skip("封存或狀態不符")
                    continue
                try:
                    d = date.fromisoformat(str(rec.get("date", ""))[:10])
                except ValueError:
                    self._skip("日期無法辨識")
                    continue
                cat = str(rec.get("categoryRaw") or "")
                item = next((v for k, v in item_map.items() if k in cat), None)
                if item is None and by_load:
                    loaded = any((st.get("weightKg") or 0) > 0 for ex in rec.get("exercises", [])
                                 for st in ex.get("sets", []))
                    item = load_item if loaded else body_item
                if item is None:
                    self._skip("類別對不到項目")
                    continue
                dates.setdefault(item, []).append(d)
                src_of.setdefault(item, f"{rel}#{item}")
        return self._build(dates, src_of)


def _hit(row: dict, flt: dict) -> bool:
    """{欄位: [子字串]}：每個欄位至少含其中一個子字串（欄位不存在視為空字串）。"""
    return all(any(v in row.get(col, "") for v in vals) for col, vals in flt.items())


def _row_ok(row: dict, flt: dict, include_any: list, exclude: dict) -> bool:
    """符合 filter 或任一條 include_any 才收；exclude 含任一個子字串就不收（優先）。"""
    if not (_hit(row, flt) or any(_hit(row, rule) for rule in include_any)):
        return False
    return not any(any(v in row.get(col, "") for v in vals) for col, vals in exclude.items())


class MarkdownTableSource:
    r"""Markdown 表格 → 候選（時間軸、送禮紀錄等，依欄位篩選；家人領域用）。

    設定：date_col、title_cols（多欄用「｜」串成標題，最多 60 字）、filter（{欄位: [子字串]}，每個欄位至少
    含其中一個才收）、exclude（同格式，含任一個就不收）、item（預設項目）、item_col＋item_map（欄位文字含有鍵就
    歸到值，先中先贏）、files／glob／exclude_files／root。表頭要同時有 date_col 與 title_cols 才算目標表；
    沒有日期的列略過；日期區間（2018-08-07~2018-08-13）取第一天。出處＝相對路徑:行號（行號不進 ID）。
    include_any：[{欄位: [子字串]}, …]，列不符合 filter、但符合任何一條（該條每個欄位至少含一個子字串）也收；
    exclude 最後判斷、優先於 include_any。item_rules：[{"col": 欄位, "contains": [子字串], "item": 項目}, …]，
    照順序先中先贏，在 item_map 之前判斷（欄位不存在或沒中就往下走）。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "md_table")

    def _files(self) -> list[Path]:
        cfg = self.cfg
        paths = [Path(p) for p in cfg.get("files", [])]
        if cfg.get("glob"):
            paths += [Path(p) for p in sorted(globmod.glob(cfg["glob"]))]
        skip = set(cfg.get("exclude_files", []))
        return [p for p in paths if p.name not in skip and p.exists()]

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        date_col, title_cols = cfg.get("date_col"), cfg["title_cols"]
        undated = bool(cfg.get("allow_undated"))
        if not date_col and not undated:
            raise KeyError("date_col（沒有日期欄的表要設 allow_undated: true）")
        flt, exc = cfg.get("filter") or {}, cfg.get("exclude") or {}
        inc, item_rules = cfg.get("include_any") or [], cfg.get("item_rules") or []
        item_col, item_map = cfg.get("item_col"), cfg.get("item_map") or {}
        root = Path(cfg["root"]) if cfg.get("root") else None
        out = []
        for path in self._files():
            rel = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else path.name
            header = None
            heading = ""
            for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
                s = line.strip()
                if s.startswith("#"):
                    heading = s.lstrip("#").strip()
                if not s.startswith("|"):
                    header = None
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if header is None:
                    if (not date_col or date_col in cells) and all(t in cells for t in title_cols):
                        header = cells
                    continue
                if re.fullmatch(r"[|\s:\-]+", s):
                    continue
                row = dict(zip(header, cells))
                if not _row_ok(row, flt, inc, exc):
                    continue
                date = normalize_date(row.get(date_col, "")) if date_col else ""
                title = "｜".join(t for t in (_clean(row.get(c, "")) for c in title_cols) if t)[:60]
                if not title or (not date and not undated):
                    continue
                text = title if cfg.get("match_on") == "title" else f"{title} {s}"      # match_on=title：只比對標題，不看整列
                if not text_gate(cfg, text) or not date_ok(cfg, date):
                    continue
                routed = route(cfg, text)
                if routed is None:
                    continue
                item = next((r["item"] for r in item_rules
                             if any(v in row.get(r["col"], "") for v in r["contains"])), None)
                if item is None and item_col:
                    item = next((v for k, v in item_map.items() if k in row.get(item_col, "")), None)
                ev = f"[{heading}] {s}"[:200] if undated and heading else s[:200]     # 沒有日期欄的表，段落標題（時期）放進證據
                out.append(_candidate({**cfg, "domain": routed[0]}, cfg.get("origin", "kb_table"), title, date,
                                      f"{rel}:{n}", ev, item or routed[1]))
        return _dedupe(out)


class TripSource:
    r"""旅程表（trips.csv）→ 家族旅遊候選，每一趟一筆（不是每個地點一筆；地點分數仍在旅遊地圖，不重複計）。

    設定：path（相對路徑以設定檔資料夾為準；欄位 trip_id,name,date_start,date_end,companions,kind）、
    filter／include_any（同 md_table：{欄位: [子字串]}，符合 filter 或任一條 include_any 才收）、domain、
    item（預設「家族旅遊」）、absorb_items（落在旅程期間內、這些項目的其他候選併進旅程，預設 ["家人大事"]，
    實際併掉由 absorb_trip_duplicates 做）。沒有 date_start 的略過並計入 skipped。
    title＝旅程名稱、date＝date_start（可為 YYYY 或 YYYY-MM）、出處＝trips.csv#<trip_id>。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "trips")
        self.skipped: dict[str, int] = {}
        self.spans: dict[str, tuple[str, str]] = {}      # 候選 ID → (期間第一天, 期間最後一天)，給 absorb_trip_duplicates

    @property
    def absorb_items(self) -> list[str]:
        v = self.cfg.get("absorb_items")
        return list(v) if v is not None else ["家人大事"]

    def candidates(self) -> list[dict]:
        cfg = self.cfg
        flt, inc = cfg.get("filter") or {}, cfg.get("include_any") or []
        path = Path(cfg["path"])
        self.skipped = {}
        self.spans = {}
        out = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                r = {k: (v or "").strip() for k, v in r.items() if k}
                if not (_hit(r, flt) or any(_hit(r, rule) for rule in inc)):
                    continue
                start, end = r.get("date_start", ""), r.get("date_end", "")
                if not r.get("name", ""):
                    self._skip("沒有名稱")
                    continue
                if not start or not DATE_RE.match(start):
                    self._skip("沒有開始日期")
                    continue
                lo = _bounds(start)[0]
                hi = _bounds(end)[1] if end and DATE_RE.match(end) else None
                if end and (hi is None or hi < lo):
                    self._skip("結束日期格式不對")                 # 當成沒有結束日期
                    hi = None
                tid = r.get("trip_id", "")
                ev = f"旅程 {tid}：{start}～{end}，同行：{r.get('companions', '')}"
                c = _candidate(cfg, "trip", r["name"], start, f"{path.name}#{tid}", ev, cfg.get("item", "家族旅遊"))
                self.spans[c["achievement_id"]] = (lo, hi or _bounds(start)[1])
                out.append(c)
        return _dedupe(out)

    def _skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def absorb_trip_duplicates(rows: list[dict], absorb_items: list[str],
                           spans: dict[str, tuple[str, str]]) -> tuple[list[dict], int]:
    """同一趟只算一筆：旅程候選（origin=trip）期間內、同領域、項目在 absorb_items 的其他候選丟掉。

    spans＝{旅程候選 ID: (期間第一天, 期間最後一天)}，由 TripSource.spans 提供（沒有結束日就用開始日的部分日期
    範圍，2019-04 → 整個 4 月）。有日期重疊（含部分日期）就算；沒有日期的不動；ID 不在 spans 的旅程列不當旅程。
    回傳 (留下的列, 被併掉的數量)。
    """
    periods = [(r["domain"], *spans[r["achievement_id"]]) for r in rows
               if r.get("origin") == "trip" and r.get("achievement_id") in spans]
    out, n = [], 0
    for r in rows:
        if r.get("origin") != "trip" and r.get("date") and r.get("item") in absorb_items:
            lo, hi = _bounds(r["date"])
            if any(r["domain"] == d and lo <= t_hi and hi >= t_lo for d, t_lo, t_hi in periods):
                n += 1
                continue
        out.append(r)
    return out, n


_TYPES = {"csv": CsvSource, "markdown": MarkdownSource, "training_log": TrainingLogSource,
          "md_table": MarkdownTableSource, "trips": TripSource, "records_json": RecordsJsonSource}


def build_sources(cfg: dict, base_dir: Path | None = None) -> list:
    """依設定建立來源；相對路徑以 base_dir（設定檔所在資料夾）為準。"""
    out = []
    for s in cfg.get("sources", []):
        s = dict(s)
        if base_dir is not None:
            for k in ("path", "root", "glob"):
                if s.get(k) and not Path(s[k]).is_absolute():
                    s[k] = str(base_dir / s[k])
            if s.get("files"):
                s["files"] = [str(p) if Path(p).is_absolute() else str(base_dir / p) for p in s["files"]]
        from .ach_sources_ext import EXT_TYPES      # 擴充來源（檔案索引、相簿事件、JSONL 事件），放在另一個檔案避免循環匯入
        types = {**_TYPES, **EXT_TYPES}
        if s.get("type") not in types:
            raise ValueError(f"不認得的來源類型：{s.get('type')}")
        for k in ("index", "catalog", "context_csv"):
            if base_dir is not None and s.get(k) and not Path(s[k]).is_absolute():
                s[k] = str(base_dir / s[k])
        out.append(types[s["type"]](s))
    return out
