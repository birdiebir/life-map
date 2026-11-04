import json
import re

import paths
from lifemap.build import build_payload, render_html


def _payload(**kw):
    return build_payload(paths.EXAMPLE_DIR, paths.REFERENCE, paths.config("levels"), paths.config("sets"),
                         paths.config("scoring"), **kw)


def test_example_payload():
    p = _payload()
    # 範例第 8 筆未確認，預設不顯示
    assert len(p["visits"]) == 7 and p["unconfirmed"] == 1
    assert p["lv"]["me"]["C-JPN"] == 4 and p["lv"]["together"]["C-JPN"] == 4
    assert "C-FRA" not in p["lv"]["together"]
    assert p["places"]["CITY-1850147"]["n"] == "東京"
    # 沒去過的城市只放精選城市（地圖上的待收集點），其他不放，避免檔案過大
    assert all("curated" in v.get("t", []) for k, v in p["places"].items()
               if k.startswith("CITY-") and k not in p["lv"]["me"])
    towns = next(s for s in p["sets"]["me"] if s["id"] == "tw_towns")
    assert towns["total"] == 368 and towns["done"] == 2


def test_include_unconfirmed():
    p = _payload(include_unconfirmed=True)
    assert len(p["visits"]) == 8 and p["lv"]["me"]["TW-10015010"] == 3


def test_render_html_is_self_contained():
    html = render_html(_payload(), paths.REFERENCE, paths.VENDOR)
    assert "/*__" not in html
    assert "http://" not in html.split("<script>")[0] and 'src="http' not in html
    m = re.search(r"const DATA = (\{.*?\});\n", html, re.S)
    assert json.loads(m.group(1))["scores"]["me"]["world"] > 0
    # 每個 <script> 都要正常結束（資料或函式庫裡的 </script> 會截斷頁面）
    assert html.count("<script>") == html.count("</script>") == 3
