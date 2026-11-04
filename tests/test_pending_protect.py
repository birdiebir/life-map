r"""takeout 匯入（merge_pending）與非 takeout 來源（照片地點、信件、相簿、社群）互不洗掉對方的列。"""
from lifemap.pending import PENDING_FIELDS, add_candidates, merge_pending, read_rows, write_rows


def r(vid, source, decision="", evidence="", place="C-JPN", ds="2024-01-01"):
    row = {f: "" for f in PENDING_FIELDS}
    row.update(visit_id=vid, place_id=place, date_start=ds, source=source, decision=decision, evidence=evidence,
               level="2", confirmed="false", together="false")
    return row


def ids(path):
    return {x["visit_id"] for x in read_rows(path)}


def test_takeout_import_keeps_non_takeout_rows(tmp_path):
    p = tmp_path / "pending.csv"
    write_rows(p, PENDING_FIELDS, [
        r("Pphoto0", "photo", "", "評論 0、照片 3；照片來源：雲端照片目錄"),      # 照片地點，沒決定
        r("Pphoto1", "photo", "y", "評論 0、照片 3；照片來源：Google 相簿 Takeout"),   # 照片地點，已收
        r("Pmail", "mail", ""),                                                        # 信件來源
        r("Palbum", "album", "y"),
        r("Pstale", "review", ""),                                                     # takeout 產生、這次沒產生、沒決定 → 丟
        r("Pstale_n", "review", "n"),                                                  # 已決定 → 留
        r("Pstale_y", "review+photo", "y"),
    ])
    merge_pending(p, [r("Pnew", "review")])
    assert ids(p) == {"Pnew", "Pphoto0", "Pphoto1", "Pmail", "Palbum", "Pstale_n", "Pstale_y"}


def test_photo_import_keeps_takeout_rows(tmp_path):
    p = tmp_path / "pending.csv"
    write_rows(p, PENDING_FIELDS, [r("Pt0", "review", ""), r("Pt1", "review+photo", "y"), r("Pt2", "photo", "n")])
    added, dup = add_candidates(p, [r("Pp", "photo", "", "照片來源：x"), r("Pt0", "photo")])
    assert (added, dup) == (1, 1)
    assert ids(p) == {"Pt0", "Pt1", "Pt2", "Pp"}


def test_roundtrip_both_orders(tmp_path):
    p = tmp_path / "pending.csv"
    add_candidates(p, [r("Pp", "photo", "", "照片來源：x"), r("Pm", "mail")])
    merge_pending(p, [r("Pt", "review")])
    assert ids(p) == {"Pp", "Pm", "Pt"}
    merge_pending(p, [])                       # 再跑一次 takeout，沒決定的 takeout 列消失，其他留著
    assert ids(p) == {"Pp", "Pm"}
