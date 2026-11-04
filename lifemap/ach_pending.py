r"""候選成就確認表 pending_achievements.csv：使用者在 decision 欄填 y（收）或 n（不收），也可以直接改 level、memory 等。

- 重新匯入：已填的決定與修改保留；n 的留著不再冒出；y 的在 apply 前也留著；已在 achievements.csv 的略過。
- apply：y 的移到 achievements.csv（confirmed=true），寫入前先驗證，有錯就整批不動。
"""
from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from .achievements import ACH_FIELDS, Domains, load_achievements
from .data import DataError, _bool
from .pending import NO, YES, read_rows, write_rows

PENDING_FIELDS = ["decision", "suggest", "reason", "certainty", "auto", *ACH_FIELDS, "evidence"]
KEEP_ON_REIMPORT = ["decision", "suggest", "reason", "certainty", "auto", "title", "date", "domain", "confidence", "item", "level",
                    "together", "memory", "photo", "privacy", "suppressed"]
# 重匯入時逐欄判斷「使用者改過沒」的欄位（旁檔 pending_achievements.auto.json 記機器基準）
TRACKED = ["title", "date", "domain", "item", "level", "confidence", "together", "memory", "photo", "privacy",
           "suppressed", "source", "evidence"]
JUDGED_KEYS = ["level", "suggest", "reason", "certainty", "title", "item", "domain", "confidence"]


def sidecar_path(pending_path: Path) -> Path:
    return pending_path.with_name(pending_path.stem + ".auto.json")


def _load_sidecar(pending_path: Path) -> tuple[dict, bool]:
    """回傳 (旁檔內容, 是否可信)。不存在＝空且可信；壞掉＝空、不可信並印警告。"""
    sp = sidecar_path(pending_path)
    if not sp.exists():
        return {}, True
    try:
        d = json.loads(sp.read_text(encoding="utf-8-sig"))
        if not isinstance(d, dict) or not all(isinstance(v, dict) for v in d.values()):
            raise ValueError("格式不是 {ID: {src, judged}}")
        return d, True
    except (OSError, ValueError) as e:
        print(f"⚠️ 旁檔 {sp.name} 讀不了（{e}），改用保守做法（保留舊值），旁檔不覆蓋", file=sys.stderr)
        return {}, False


def _save_sidecar(pending_path: Path, data: dict) -> None:
    sp = sidecar_path(pending_path)
    sp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


BOOL_FIELDS = {"together", "suppressed", "confirmed"}


def _s(v) -> str:
    return str(v or "").strip()


def _norm(field: str, v) -> str:
    """比對用的正規化：去前後空白；布林欄位 false／FALSE／0／空白視為同一值（照 data._bool）。"""
    t = _s(v)
    if field in BOOL_FIELDS:
        b = _bool(t)
        if b is not None:
            return "true" if b else "false"
    return t


def _src_of(row: dict) -> dict:
    return {f: _s(row.get(f, "")) for f in TRACKED}


def _is_manual(row: dict) -> bool:
    return _s(row.get("origin", "")).lower() == "manual"


def _dict_of(ent: dict | None, key: str, aid: str) -> dict:
    v = ent.get(key) if ent else None
    if v is None:
        return {}
    if not isinstance(v, dict):
        print(f"⚠️ 旁檔 {aid} 的 {key} 不是 dict，當成空的", file=sys.stderr)
        return {}
    return dict(v)


def _find_relinks(old: dict, side: dict, new_rows: list[dict], existing_ids: set[str]) -> dict[str, str]:
    """標題改字使 ID 變了：本次新列（沒對到舊 ID）與沒被產生的舊列，source 與 domain 完全相同且一對一，視為同一筆。"""
    produced = {r["achievement_id"] for r in new_rows}
    new_by: dict = {}
    for r in new_rows:
        aid = r["achievement_id"]
        if aid in old or aid in existing_ids:
            continue
        new_by.setdefault((_s(r.get("source")), _s(r.get("domain"))), []).append(aid)
    old_by: dict = {}
    for oid, o in old.items():
        if oid in produced or oid in existing_ids or o.get("decision") or _is_manual(o):
            continue
        src = _dict_of(side.get(oid), "src", oid)
        key = (_s(src.get("source", o.get("source"))), _s(src.get("domain", o.get("domain"))))
        old_by.setdefault(key, []).append(oid)
    return {n[0]: old_by[k][0] for k, n in new_by.items() if k[0] and len(n) == 1 and len(old_by.get(k, [])) == 1}


def _touched(o: dict, ent: dict | None, judged: dict) -> bool:
    """舊列有沒有被判斷或使用者動過（動過的不能默默丟）。"""
    if judged or o.get("suggest") or o.get("reason"):
        return True
    if ent is None:
        return bool(o.get("memory") or o.get("photo"))
    base = {**_dict_of(ent, "src", ""), **judged}
    return any(_norm(f, o.get(f, "")) != _norm(f, base.get(f, "")) for f in TRACKED)


def merge_pending(path: Path, new_rows: list[dict], existing_ids: set[str]) -> list[dict]:
    """重匯入：使用者改過的欄位、判斷值、已決定的列、手動列都保留；沒改過的欄位跟著來源更新。

    來源文字改了使 ID 變（同 source 同 domain 一對一）會重新連結，把舊列的判斷與修改帶到新 ID。
    """
    old = {r["achievement_id"]: r for r in read_rows(path)}
    side, trusted = _load_sidecar(path)
    new_side: dict = {}
    merged = []
    relink = _find_relinks(old, side, new_rows, existing_ids)
    for r in new_rows:
        aid = r["achievement_id"]
        if aid in existing_ids:
            old.pop(aid, None)
            continue
        oid = relink.get(aid, aid)
        if oid != aid:
            print(f"ID 換了：{oid} → {aid}（{r.get('title', '')}）")
        o = old.pop(oid, None)
        ent = side.get(oid)
        judged = _dict_of(ent, "judged", oid)
        if o is None:
            # 新列；若旁檔有這個 ID 的紀錄（使用者在 Excel 刪掉又被重新產生），沿用 judged 並套回
            merged.append({**r, **judged})
            new_side[aid] = {"src": _src_of(r), "judged": judged}
            continue
        out = {**r}
        if o.get("decision"):                      # 已決定：使用者看著那一版決定的，全部保留
            out.update({k: o[k] for k in PENDING_FIELDS if k in o and k != "achievement_id"})
        elif ent is None:                          # 沒有旁檔紀錄的舊列：保守保留舊值，並補寫旁檔
            out.update({k: o[k] for k in KEEP_ON_REIMPORT if o.get(k)})
            out.update({k: o[k] for k in ("source", "evidence") if o.get(k)})
            if o.get("suggest"):
                judged = {k: o[k] for k in ("level", "suggest", "reason") if k in o}
                if o.get("certainty"):
                    judged["certainty"] = o["certainty"]
        else:
            base = {**_dict_of(ent, "src", oid), **judged}
            for f in TRACKED:
                ov = o.get(f, "")
                if _norm(f, ov) != _norm(f, base.get(f, "")):
                    out[f] = ov                    # 規則 1：使用者改過
                elif f in judged:
                    out[f] = judged[f]             # 規則 2：判斷值
                # 規則 3：其他用新來源值（out 已是新值）
            out.update({k: o[k] for k in ("decision", "suggest", "reason", "certainty", "auto") if k in o})
        merged.append(out)
        new_side[aid] = {"src": _src_of(r), "judged": judged}
    for oid, o in old.items():
        if oid in existing_ids:
            continue
        ent = side.get(oid)
        if o.get("decision") or _is_manual(o):
            merged.append(o)                       # 已決定、或手動列（來源不會再產生）
        elif _touched(o, ent, _dict_of(ent, "judged", oid)):
            print(f"⚠️ 來源已不再產生，保留：{oid}（{o.get('title', '')}）", file=sys.stderr)
            merged.append(o)
        else:
            continue                               # 完全沒動過的機器列：丟掉
        if oid in side:
            new_side[oid] = side[oid]
    merged.sort(key=lambda r: (r.get("date", "") == "", r.get("date", ""), r["achievement_id"]))
    write_rows(path, PENDING_FIELDS, merged)
    if trusted:
        _save_sidecar(path, new_side)
    return merged


def apply_pending(data_dir: Path, domains: Domains) -> dict:
    pending_path = data_dir / "pending_achievements.csv"
    rows = read_rows(pending_path)
    bad = [f"{r['achievement_id']}：{r['decision']}" for r in rows
           if r.get("decision", "").lower() not in YES | NO | {""}]
    if bad:
        raise DataError("decision 只能填 y／n 或留空：" + "、".join(bad))
    accept = [r for r in rows if r.get("decision", "").lower() in YES]
    if not accept:
        return {"accepted": 0, "kept": len(rows)}

    ach_path = data_dir / "achievements.csv"
    current = read_rows(ach_path)
    have = {r["achievement_id"] for r in current}
    for r in accept:
        if r["achievement_id"] in have:
            continue
        current.append({**{k: r.get(k, "") for k in ACH_FIELDS}, "confirmed": "true",
                        "together": "true" if _bool(r.get("together", "")) else "false",
                        "suppressed": "true" if _bool(r.get("suppressed", "")) else "false"})
    tmp = ach_path.with_suffix(".tmp")
    write_rows(tmp, ACH_FIELDS, current)
    try:
        load_achievements(tmp, domains)  # 寫入前再驗一次，有錯就不覆蓋
    except DataError as e:
        tmp.unlink(missing_ok=True)
        ids = [r["achievement_id"] for r in current]  # 第 N 列＝表頭後第 N-1 筆
        msg = re.sub(r"第 (\d+) 列", lambda m: f"{ids[int(m.group(1)) - 2]}"
                     if 0 <= int(m.group(1)) - 2 < len(ids) else m.group(0), str(e))
        raise DataError(msg) from None
    tmp.replace(ach_path)

    keep = [r for r in rows if r not in accept]
    write_rows(pending_path, PENDING_FIELDS, keep)
    side, trusted = _load_sidecar(pending_path)
    if trusted and side:
        for r in accept:
            side.pop(r["achievement_id"], None)
        _save_sidecar(pending_path, side)
    return {"accepted": len(accept), "kept": len(keep)}


CERTAINTY = ("高", "低")
NEVER_AUTO_PREFIXES = ("fb_", "ig_")      # Facebook／Instagram 來源（origin 以此開頭）的候選：把握度強制低、永遠不自動決定


def never_auto(row: dict) -> bool:
    """社群平台來源的候選（origin 以 fb_／ig_ 開頭）：要使用者自己確認，auto_decide 不會碰，判斷時把握度也強制「低」。"""
    return str(row.get("origin", "")).strip().lower().startswith(NEVER_AUTO_PREFIXES)


def _norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", t or "").lower()


def _src_file(source: str) -> str:
    return re.sub(r":\d+$", "", source or "").replace(chr(92), "/").split("/")[-1].split("#")[0]


def find_duplicates(row: dict, pool: list[dict], min_ratio: float = 0.7) -> list[dict]:
    """find_duplicate 的完整版：回傳 pool 裡所有疑似同一件事的舊列（同領域，且標題正規化後相同，或同一個來源檔、標題相似度 >= min_ratio）。"""
    t = _norm_title(row.get("title", ""))
    f = _src_file(row.get("source", ""))
    out = []
    for o in pool:
        if o.get("achievement_id") == row.get("achievement_id") or o.get("domain") != row.get("domain"):
            continue
        ot = _norm_title(o.get("title", ""))
        if t and t == ot:
            out.append(o)
        elif f and f == _src_file(o.get("source", "")) and t and ot and SequenceMatcher(None, t, ot).ratio() >= min_ratio:
            out.append(o)
    return out


def find_duplicate(row: dict, pool: list[dict], min_ratio: float = 0.7) -> str:
    """候選跟已收進主檔／已決定的列疑似同一件事（KB 一改，ID 就換，會被當成新候選）：同領域，且
    標題正規化後相同（去標點空白、不分大小寫），或同一個來源檔、標題相似度 >= min_ratio。回傳對到的舊 ID，沒有就空字串。"""
    hits = find_duplicates(row, pool, min_ratio)
    return hits[0]["achievement_id"] if hits else ""


def decided_pool(pending_path: Path, rows: list[dict]) -> list[dict]:
    """比對用的舊列：achievements.csv（同資料夾）全部 ＋ 確認表裡已有 decision 的列。"""
    ach = pending_path.with_name("achievements.csv")
    return read_rows(ach) + [r for r in rows if r.get("decision")]


def is_auto(row: dict) -> bool:
    """decision 是自動填的（auto 欄記著當時填的值）；使用者之後改了 decision 就不算自動。"""
    return bool(row.get("auto")) and row.get("auto", "").lower() == row.get("decision", "").lower()


def auto_decide(pending_path: Path, default_certainty: str = "") -> dict:
    """預設照 Opus 建議：還沒有 decision、有 suggest 且把握度「高」的列，suggest=y 填 y、suggest=n 填 n，
    auto 欄記下自動填的值（之後使用者改 decision 仍以使用者為準，改了就不再算自動）。把握度「低」或空白的不動，
    留給 routine 開題問使用者。default_certainty：把握度空白的列視為這個值（只在套用現有批次時用，不寫回 certainty 以外的欄位）。
    例外：疑似重複對到的舊列是已決定「不收」、而這次 suggest 也是 n → 直接自動填 n（不分把握度，reason 註明舊 ID），算進 auto_n。
    已有 decision 的列一律不碰；auto 有值但 decision 被清空的列視為使用者撤回，不再自動填（算進 ask_user）。回傳計數。
    """
    if default_certainty and default_certainty not in CERTAINTY:
        raise DataError(f"default_certainty 只能是 高 或 低：{default_certainty}")
    rows = read_rows(pending_path)
    pool = decided_pool(pending_path, rows)
    n_y = n_n = n_low = n_nosuggest = n_dup = 0
    changed = False
    for r in rows:
        if r.get("decision"):
            continue
        if never_auto(r):                          # 社群來源：把握度強制低，留給使用者
            if r.get("certainty") != "低":
                r["certainty"] = "低"
                changed = True
            if r.get("suggest", "").lower() in ("y", "n"):
                n_low += 1
            else:
                n_nosuggest += 1
            continue
        sg = r.get("suggest", "").lower()
        if sg not in ("y", "n"):
            n_nosuggest += 1
            continue
        hits = find_duplicates(r, pool)
        dup = hits[0]["achievement_id"] if hits else ""
        refused = next((o for o in hits if o.get("decision", "").lower() in NO), None)
        if refused and sg == "n" and not r.get("auto"):
            # 舊列是已決定「不收」、這次 suggest 也是 n：問了也只是照舊，直接自動填 n（auto 記下來），不問使用者
            tag = f"同於已決定不收的 {refused['achievement_id']}"
            r["reason"] = (r.get("reason", "") + "；" + tag).lstrip("；") if tag not in r.get("reason", "") else r["reason"]
            r["decision"] = r["auto"] = "n"
            n_n += 1
            changed = True
            continue
        if dup:                                    # 疑似舊東西換 ID 重新冒出：不自動決定、把握度強制低、reason 註明
            tag = f"疑似重複：{dup}"
            if tag not in r.get("reason", ""):
                r["reason"] = (r.get("reason", "") + "；" + tag).lstrip("；")
            r["certainty"] = "低"
            n_dup += 1
            n_low += 1
            changed = True
            continue
        if r.get("auto"):                          # 自動填過、現在 decision 被使用者清空＝撤回，不再自動填，留給使用者
            n_low += 1
            continue
        if not r.get("certainty") and default_certainty:
            r["certainty"] = default_certainty
        if r.get("certainty") != "高":
            n_low += 1
            continue
        r["decision"] = r["auto"] = sg
        if sg == "y":
            n_y += 1
        else:
            n_n += 1
    if n_y or n_n or default_certainty or changed:
        write_rows(pending_path, PENDING_FIELDS, rows)
    return {"auto_y": n_y, "auto_n": n_n, "ask_user": n_low, "no_suggest": n_nosuggest, "suspected_dup": n_dup}


def apply_judgments(pending_path: Path, judgments: list[dict], domains: Domains) -> dict:
    """把 Opus 的等級判斷寫進確認表（level／suggest／reason，選填 title／item／domain／confidence）。

    一次驗證全部，有錯整批不寫；已填 decision 的列不覆蓋；只寫 pending，不碰 achievements.csv。
    """
    rows = read_rows(pending_path)
    by_id = {r["achievement_id"]: r for r in rows}
    errors = []
    seen_ids: set[str] = set()
    for i, j in enumerate(judgments, start=1):
        aid = j.get("achievement_id", "")
        errs = []
        if aid not in by_id:
            errs.append("ID 不在確認表裡")
        if aid in seen_ids:
            errs.append("同一個 ID 在判斷檔裡出現不只一次")
        seen_ids.add(aid)
        lv = j.get("level")
        if isinstance(lv, str) and re.fullmatch(r"\d+", lv.strip()):
            lv = int(lv)
        if isinstance(lv, bool) or not isinstance(lv, int) or not 0 <= lv <= 5:
            errs.append(f"level 要是 0～5 的整數：{j.get('level')}")
        if str(j.get("suggest", "")).lower() not in ("y", "n"):
            errs.append(f"suggest 只能是 y 或 n：{j.get('suggest')}")
        if j.get("certainty") and str(j["certainty"]) not in CERTAINTY:
            errs.append(f"certainty 只能是 高 或 低：{j.get('certainty')}")
        if j.get("domain") and j["domain"] not in domains.by_id:
            errs.append(f"領域不存在：{j['domain']}")
        if errs:
            errors.append(f"第 {i} 筆（{aid}）：" + "；".join(errs))
    if errors:
        raise DataError(f"判斷檔有 {len(errors)} 筆要修正，整批沒有寫入：\n" + "\n".join(errors))
    applied = skipped = 0
    side, trusted = _load_sidecar(pending_path)
    for j in judgments:
        r = by_id[j["achievement_id"]]
        if r.get("decision"):
            skipped += 1
            continue
        ent = side.setdefault(r["achievement_id"], {"src": _src_of(r), "judged": {}})  # 補寫前的值當機器基準
        if not isinstance(ent.get("judged"), dict):
            ent["judged"] = {}
        r["level"] = str(int(j["level"]))
        r["suggest"] = str(j["suggest"]).lower()
        r["reason"] = j.get("reason", "")
        jj = dict(j)
        if never_auto(r):                          # 社群來源：不管判斷檔怎麼寫，把握度都是低
            jj["certainty"] = "低"
        if jj.get("certainty"):
            r["certainty"] = str(jj["certainty"])
        for k in ("title", "item", "domain", "confidence"):
            if j.get(k):
                r[k] = j[k]
        ent.setdefault("judged", {}).update({k: r.get(k, "") for k in JUDGED_KEYS
                                              if k in ("level", "suggest", "reason") or jj.get(k)})
        applied += 1
    if applied:
        write_rows(pending_path, PENDING_FIELDS, rows)
        if trusted:
            _save_sidecar(pending_path, side)
    return {"applied": applied, "skipped_decided": skipped}
