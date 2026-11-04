# life-map：人生成就地圖

## 這是什麼

把旅遊足跡做成可以收集的離線地圖：世界（國家＋城市）、台灣（22 縣市＋368 鄉鎮），每個地方依「經驗值」0～5 級上色，附回憶卡與收集進度；也可以把運動、學習、冒險、人際、家人、職涯等人生成就整理成卡片牆與雷達圖。資料全部放在本機，地點判斷離線完成，不呼叫任何外部地理編碼服務。輸出是單一自包含的 HTML 檔，用瀏覽器直接打開。

授權：MIT（見 `LICENSE`）；內含的參考資料與第三方程式庫各有授權，見最下方「Data sources & licenses」。

## 用範例資料跑起來

需要 Python 3.10 以上與 pytest（只有執行測試時需要）。專案附有 `private.example\` 假資料，沒有 `private\` 時會自動改用它：

```
git clone <this repo>
cd life-map
python scripts\build_map.py
```

產出 `private\output\life-map.html`（沒有 `private\` 時在 `private.example\output\`），用瀏覽器打開。要跑測試：`python -X utf8 -m pytest -q`。

要換成自己的資料：把 `private.example\` 複製成 `private\`，改裡面的 `visits.csv`（可以用 Excel 編輯）。`private\` 已列入 `.gitignore`，不會被提交。

- 規格：`docs\規格書_第一階段旅遊地圖.md`
- 開發日誌：`docs\開發日誌.md`

## 快速開始

```
python scripts\build_map.py
```

產出 `private\output\life-map.html`，用瀏覽器打開即可（完全離線）。沒有 `private\` 時會改用 `private.example\` 的假資料。網址後面可加 `#taiwan`、`#taiwan/county`、`#together` 指定初始檢視。

`--include-unconfirmed`：連還沒確認的候選足跡一起畫。

## 自己的足跡

把 `private.example\` 複製成 `private\`，改 `visits.csv`（可以用 Excel 編輯）：

| 欄位 | 說明 |
|---|---|
| place_id | 地點 ID：國家 `C-JPN`、城市 `CITY-<GeoNames ID>`、台灣縣市 `TW-63000`、鄉鎮 `TW-63000030`（查 `reference\` 的 CSV） |
| date_start／date_end | `YYYY`、`YYYY-MM`、`YYYY-MM-DD` 或空白 |
| level | 0 沒去過、1 路過、2 踏上、3 遊玩、4 過夜、5 住過 |
| together | 是否跟伴侶一起（true／false），「一起」檢視用 |
| confirmed | false 的是候選足跡，預設不顯示 |

## 從 Google Takeout 回填過去的足跡

1. 在 `private\sources.json` 寫 Takeout zip 路徑：`{"takeout_zips": ["D:\\...\\takeout-xxx.zip"]}`（zip 只唯讀，不解壓）。
2. `python scripts\import_takeout.py`：讀地圖評論和上傳到地圖的照片（座標＋日期），離線判斷地點、分旅程、推等級，產生 `private\pending.csv`。已經有足跡涵蓋的會略過。
3. `python scripts\build_map.py --include-unconfirmed`：產生 `life-map_預覽.html`，先看候選畫上去的樣子。
4. 用 Excel 開 `pending.csv`，在 `decision` 欄填 `y`（收）或 `n`（不收）；也可以直接改 `level`、`together`、`memory`。
5. `python scripts\apply_pending.py`：`y` 的收進 `visits.csv`，代表照片從 zip 取出到 `private\photos\`；`n` 的留在表裡，重新匯入也不會再冒出來。
6. `python scripts\build_map.py` 更新正式地圖。

推定規則（門檻在 `config\import.json`）：同一範圍（台灣看縣市、國外看國家）相隔 3 天內算同一趟；同一趟在同一地點出現 2 天以上推 4 過夜、同一天 2 筆以上推 3 遊玩、只有 1 筆推 2 踏上。「住過」不會自動推，要自己改成 5。

## 之後怎麼更新（第一階段收尾時的做法）

- **新的一趟旅行**：在 `private\visits.csv` 加列（可以用 Excel），或下次匯出 Takeout 後在 `private\sources.json` 加 zip 路徑、跑 `import_takeout.py` → 審 `pending.csv` → `apply_pending.py`。
- 更新地圖：`python scripts\build_map.py`。
- **同步到筆記庫**（Markdown 筆記，例如 Obsidian）：`python scripts\sync_kb.py --dry-run` 看差異，確認只是新增或更新後 `--apply`（寫入並 commit，只 add 那一篇）。只改踩點表裡 `<!-- life-map:auto:start/end -->` 之間的收集進度區塊，手寫內容不動；有項目減少或變動超過 40 行會拒絕，人看過再加 `--force`。通用設定（要列哪些套組、上限）在 `config\kb_sync.json`；筆記庫路徑與筆記是個人值，放 `private\kb_sync.json`（範本 `private.example\kb_sync.json`）。
- **偵測新旅程資料**：`python scripts\check_new.py`（給 routine 呼叫）輸出一行，有新資料結束碼 10。監看 `private\sources.json` 的 `takeout_zips` 和 `watch_dirs`（資料夾，找 `takeout*.zip`），基準是上次匯入（`import_takeout.py` 會寫 `private\import_state.json`），沒有紀錄時用 `pending.csv` 的修改時間。有新資料才跑 `import_takeout.py` → 審 `pending.csv` → `apply_pending.py` → `build_map.py` → `sync_kb.py`。
- **照片地點**：`python scripts\import_photo_locations.py [--write]`。讀 `private\sources.json` 的 `photo_sources`：`catalog_csv`（照片目錄 CSV，沒有座標的列會略過，欄位 `gps`＝「緯度,經度」、`date_taken`、`date_precision`，只收 day 精度）和 `google_photos_dir`（Google 相簿 Takeout 解壓後的資料夾，讀每張照片旁的 JSON：`photoTakenTime`、`geoDataExif`／`geoData`，0,0 視為沒有；範例欄位已放著、`enabled: false`）。座標離線對到既有地點庫，同一地點同一天合併，已在 `visits.csv` 的不重複，結果只新增進 `pending.csv`（evidence 結尾標「照片來源：…」，確認表原有的列不動），之後照上面的審核流程。座標不寫進任何檔案。預設試跑，`--write` 才寫。
- **Takeout 解壓到外接硬碟後、刪暫存前**：把 `google_photos_dir` 那項的 `path` 改成解壓出來的「Google 相簿」資料夾、拿掉 `enabled: false`，跑一次 `import_photo_locations.py`（再 `--write`），才把暫存刪掉。
- 台灣的百岳、老街、離島套組預設關閉（`config\sets.json` 的 `enabled`），想收集再打開。

## 出入境紀錄（選用）

`private\border_crossings.csv`（欄位 exit_date、entry_date、destination、note，日期 YYYY-MM-DD）。台灣可以向移民署申請「入出國日期證明書」。有這份檔案時，匯入會用它判斷那天人在不在國內：人在國外時寫的本國評論，日期清空、信心低；國外的候選如果不在任何出入境期間內，信心降低。

規則都在 `config\`：等級顏色與「去過」門檻（`levels.json`）、要顯示哪些套組（`sets.json`）、經驗值怎麼算（`scoring.json`）。

## 人生成就（第二階段，開發中）

M1／M1b 做資料模型、候選來源與去雜訊規則；HTML 已有「人生成就」分頁（七格總覽＋七軸雷達、領域詳情、依年份看）：產出的頁面上方按「人生成就」，或網址加 `#ach`、`#ach/<領域>`、`#ach/year`；`python scripts\build_map.py --include-unconfirmed` 產生的預覽會把 pending_achievements.csv 裡有填等級、沒被否決的候選也算進來，卡片標「待確認」（`config\domains.json` 的 `radar.travel_kind`／`top_n` 決定旅遊軸取法）。（設計文件為作者個人規劃，未公開。）

檔案（個人的放 `private\`，範例在 `private.example\`）：

| 檔案 | 說明 |
|---|---|
| `config\domains.json` | 六個領域（運動、學習、冒險、人際、家人、職涯）的 1～5 級定義、各級分數（可改）、套組、雷達前幾名（`top_n`）、隱私等級 |
| `achievements.csv` | 成就主資料，用 Excel 編輯也可以 |
| `pending_achievements.csv` | 候選，欄位 `decision`（你填 `y`／`n`）、`suggest`／`reason`（Opus 的建議與等級理由）＋成就欄位＋`evidence`；`import_achievements.py --write` 會寫入，重匯入會保留你改過的欄位；decision 填好 `y` 的收進主檔用 `scripts\apply_achievements.py`（見下方） |
| `config\ach_rules.json` | 通用的候選去雜訊（`noise`）與項目對應（`item_rules`）規則 |
| `achievement_rules.json` | 個人規則，同結構；list 欄位（`drop_title_patterns`、`signals`、`item_rules`）private 排前面、優先命中，純量欄位（`min_title_chars`、`require_signal`）private 覆蓋 |
| `achievement_sets.json` | 個人套組：`{"learning": [{"id","name","items"}]}`，同 id 取代 `domains.json` 的通用套組、新 id 附加 |
| `achievement_sources.json` | 候選來源設定（CSV 或 KB 筆記，路徑自己填） |
| `achievement_suppress.json` | 整段「不再提起」規則（領域／項目／日期區間，欄位都可省略） |

`achievements.csv` 欄位：

| 欄位 | 說明 |
|---|---|
| achievement_id、domain、item、title | ID（不可重複）、領域 ID、項目（例：羽球）、標題 |
| level | 0～5，項目等級取該項目所有已確認紀錄的最高級（只升不降） |
| date | `YYYY`、`YYYY-MM`、`YYYY-MM-DD` 或空白 |
| together | 是否一起完成（true／false） |
| memory、photo、source、origin、confidence | 回憶、照片路徑、出處、來源類型、把握度 |
| confirmed | false 的不算（候選） |
| privacy | `local`（只放本機）或 `kb`（標題可同步到 KB）；空白＝領域預設 |
| suppressed | true＝不再提起：等級、經驗值、雷達照算，但不出現在卡牆、依年份看、最近一張卡 |

試跑候選來源（不寫任何檔案）：

```
python scripts\import_achievements.py --dry-run --example   # 用 private.example 的假資料
python scripts\import_achievements.py --dry-run             # 用 private\achievement_sources.json
```

確認沒問題才加 `--write`（寫進 `private\pending_achievements.csv`）。

## 重建參考資料

`reference\` 已經建好，一般不用重建。要更新時，把下列檔案放進同一個資料夾，再跑 `python scripts\build_reference.py --src <資料夾>`（需要 node）：

- `countries-50m.json`（npm `world-atlas`）
- `towns-10t.json`（npm `taiwan-atlas`；套件內中文名已損毀，中文名改用下一項）
- `nlsc\county.xml`、`nlsc\town_<縣市字母>.xml`（內政部國土測繪中心 `https://api.nlsc.gov.tw/other/ListCounty`、`/ListTown1/<字母>`）
- `countryInfo.txt`、`cities15000.txt`（GeoNames）
- `d3.min.js`（npm `d3@7`）、`topojson-client.min.js`

## Data sources & licenses

| 資料 | 來源 | 授權 |
|---|---|---|
| 世界國界 | Natural Earth（經 world-atlas） | 公有領域（world-atlas ISC） |
| 台灣縣市鄉鎮界線 | 內政部（經 taiwan-atlas） | 政府資料開放授權條款（taiwan-atlas MIT） |
| 台灣行政區中文名 | 內政部國土測繪中心 API | 政府資料開放授權條款 |
| 國家、城市 | GeoNames | CC BY 4.0 |
| D3、topojson-client | Mike Bostock | ISC |
| 世界遺產（`reference\world\whs.csv`） | UNESCO 開放資料平台 data.unesco.org 資料集 whc001（https://data.unesco.org/explore/dataset/whc001/ ，2026-11-04 查詢資料集授權欄為 CC BY-SA 4.0）；缺的座標與繁中名補自 Wikidata，部分中文名由 UNESCO 簡中以 OpenCC 轉換；本專案只保留部分欄位 | CC BY-SA 4.0（© UNESCO；Wikidata CC0）。注意：whc.unesco.org 網站本身的資料另有「轉載需書面授權」條款，本專案只取用 data.unesco.org 以 CC BY-SA 4.0 釋出的資料集 |
| 城市排名（`city_lists.csv`） | Euromonitor Top 100 City Destinations（公開新聞稿的名次、2025 旅客前 10、2018 旅客前 100）、EIU Global Liveability（公開名次） | 只收排名事實與出處網址 |
| 旅遊警示（`travel_warnings.csv`） | 外交部領事事務局國外旅遊警示（2026-10-12 擷取） | 政府資料 |
| 聯合國會員國（`un_members.csv`） | un.org Member States | — |
| 台灣景點（`reference\taiwan\poi.csv`） | 第一層：內政部國家公園署、交通部觀光署；第二層：觀光署「國內主要觀光遊憩據點遊客人數」2024（data.gov.tw #8116）＋觀光資訊資料庫景點座標；百岳、部分座標：維基百科；約 15 筆座標：OpenStreetMap | 政府資料開放授權條款第 1 版；維基 CC BY-SA 4.0；© OpenStreetMap contributors（ODbL） |


### 補充說明

- 第三方程式庫放在 `vendor\`：`d3.min.js`（D3 v7.9.0，ISC，授權全文 `vendor\LICENSE.d3.txt`）、`topojson-client.min.js`（topojson-client v3.1.0，ISC，授權全文 `vendor\LICENSE.topojson-client.txt`）。
- 地圖形狀經由 npm 套件轉出：世界國界來自 `world-atlas` 2.0.2（ISC，`reference\world\LICENSE.world-atlas.txt`；底層資料 Natural Earth 為公有領域）、台灣鄉鎮界線來自 `taiwan-atlas`（MIT，`reference\taiwan\LICENSE.taiwan-atlas.txt`；底層資料為內政部公開資料）。
- 國家與城市（`reference\world\countries.csv`、`cities.csv`）：GeoNames（CC BY 4.0，需標示出處 GeoNames, https://www.geonames.org/）；本專案只保留部分欄位（精簡過，非原始檔）。國名中文由 Node `Intl.DisplayNames`（zh-Hant-TW）產生。
- `reference\world\city_names_zh.csv`（城市中文名）：只收範例資料會用到的幾個城市，中文名為作者自行翻譯的通用譯名。要補其他城市，自己建 `city_names_zh.local.csv`（同欄位 `id,name_zh`，已列入 `.gitignore`），會蓋過同 ID 的名稱；沒有中文名的城市顯示英文名。
- 台灣行政區中文名（`counties.csv`、`towns.csv`）：內政部國土測繪中心公開 API，政府資料開放授權條款。
- `reference\world\travel_warnings.csv` 的內容為外交部公開資訊的擷取，使用前請自行確認最新版與授權條款；`city_lists.csv` 只收排名事實與出處網址。
- 若你在自己的專案重新散布 `reference\` 內的資料，請保留上述出處標示；CC BY-SA 4.0 的資料（世界遺產清單、部分景點座標）衍生物需以相同條款分享。

精選城市（`reference\world\curated_cities.csv`）由 `scripts\build_reference_m3.py` 依規格書 §6.2 產生：候選＝首都、百萬人口城市、名單上的城市；排除外交部全國紅／橙色警示；至少符合 Euromonitor 任一名單、EIU 前 50、20 km 內有世界遺產其中一項。`status` 欄可以手動改（include／exclude），重建時會保留。

## 測試

```
python -m pytest -q
```

### 去雜訊與項目對應（`config\ach_rules.json`）

```
{"noise": {"apply_to_origins": ["kb_note"], "min_title_chars": 6,
           "drop_title_patterns": [regex…], "require_signal": true, "signals": [關鍵字或 regex…]},
 "item_rules": [{"pattern": regex, "item": "…", "domain": "可省略", "domains": ["可省略"], "field": "title|file|any"}]}
```

`domains`（選填）：這條規則只套用到這些領域的候選（例如學習類規則寫 `["learning"]`，職涯表的「Master of Science 畢業」就不會被改成碩士）；沒寫就套用到全部領域。`domain`（單數）則是命中後把候選改成的領域。`config\ach_rules.json` 只放通用規則；跟你自己的筆記寫法綁定的規則（課程代碼格式、學費金額、特定證照等）放 `private\achievement_rules.json`。

- noise 只套用在 `apply_to_origins` 的候選（職涯表是人工整理的 CSV，不擋）。標題命中 `drop_title_patterns` 就丟；標題短於 `min_title_chars` 且標題沒有 signal 就丟；`require_signal` 為 true 時，標題＋證據裡沒有任何 signal 也丟。
- item_rules 依序比對，第一條命中就用（`field` 決定比對標題、出處檔名或兩者）；沒命中保留來源設定的預設項目。
- 整份筆記都不是成就（例如群組時間軸）：加進 `achievement_sources.json` 對應來源的 `exclude`。
- `import_achievements.py` 跑完所有來源後依序：去雜訊 → 項目對應 → 跨來源去重複（標題＋日期；先去雜訊才不會讓好的那筆被同標題的雜訊筆一起去掉），並印出每個項目的筆數與各規則擋掉的筆數。

### 運動候選來源 records_json

運動候選讀紀錄 app 匯出的 `records\fitness-sessions.json`（來源類型 `records_json`，`RecordsJsonSource`）：每個運動項目一筆候選，等級規則跟 `training_log` 一樣（期間、有紀錄週數、涵蓋率 `min_coverage`）。設定：`files`、`item_map`（`categoryRaw` 含鍵就歸到值）、`status`（預設 `["done"]`，封存的略過）、`infer_by_load`（沒對到 `item_map` 時依有沒有重量分重訓／徒手訓練，`load_item`／`bodyweight_item` 可改名）。evidence 只寫期間與週數。範例 `private.example\ach_src\範例健身紀錄.json`。個人設定把原本讀筆記庫健身筆記的 `training_log` 換成這個；換來源後出處字串不同，候選 ID 會換，舊的運動候選已決定的就留著，新的會當新候選再出現一次（只升不降，不影響等級）。

### 等級判斷（Opus 建議）

候選的等級要 Opus 判斷。把結果存成 `judgments.json`：

```
[{"achievement_id": "A-xxxx", "level": 4, "suggest": "y", "reason": "L4：獲獎", "title": "可省略", "item": "可省略", "domain": "可省略", "confidence": "可省略"}]
```

```
python scripts\apply_judgments.py judgments.json          # 預設只驗證、印摘要
python scripts\apply_judgments.py judgments.json --write  # 真的寫入 pending
```

一次驗證全部（ID 不在表裡、level 不是 0～5、suggest 不是 y／n、領域不存在），有錯整批不寫；你已經填了 `decision` 的列不覆蓋；只寫 `pending_achievements.csv`，絕不動 `achievements.csv`。

### 收進主檔

```
python scripts\apply_achievements.py            # 預設試跑：只印會收幾筆、留幾筆，什麼都不寫
python scripts\apply_achievements.py --write    # 真的把 decision=y 的收進 achievements.csv
```

`--data-dir` 可指到別的資料夾（預設 `private\`）。`decision` 只能填 `y`／`n` 或留空，有別的值整批不動。

### 來源擴充：檔名清單、相簿事件、JSONL 事件、足跡事件

- 所有來源通用：`origin`（覆蓋預設，社群平台用 `fb_`／`ig_` 開頭）、`require_any`／`drop_any`（regex，來源層級雜訊閘門）、`domain_rules`（`[{match, domain, item, drop}]` 先中先贏，`drop_unmatched` 沒命中就丟）、`date_max`（`today` 或日期，晚於它的丟掉）、`match_on: title`（`markdown`／`md_table` 只比對標題）。
- `file_index`：`index`（INDEX.md）＋`section_contains`，或 `glob`＋`root`（沒有 INDEX.md 的資料夾，標題＝檔名）；`date_fallback: mtime` 才用修改日；`exts`、`exclude_files`。只讀檔名與摘要，不讀檔案內容。
- `photo_albums`：`catalog`（照片目錄 CSV）、`group_by`（`line_album`／`folder`）、`rules`（沒命中規則的相簿不收）、`min_photos`、`outlier_days`、`context_csv`（資料夾背景表，照片沒日期時補）。
- `jsonl_events`：`files`、`date_field`、`text_field`、`include`／`exclude`、`title_regex`、`evidence_fields`、`origin`（必填）。
- `md_table` 沒有日期欄：`allow_undated: true`。
- 旅遊足跡：`python scripts\import_event_places.py [--write]`，`sources.json` 的 `place_event_sources`（`album_places`、`jsonl_places`，規則 `{match, place_id 或 place_ids, level, together}`），只新增進 `pending.csv`。
- 社群來源（`fb_`／`ig_` origin）：判斷時把握度強制低、`--auto-decide` 永遠不碰，一定要使用者自己確認。
- 疑似重複：`--auto-decide` 前會把新候選跟 `achievements.csv` 與已決定的列比對（同領域、標題正規化後相同，或同來源檔且相似度 >= 0.7），比到的不自動決定、把握度強制低、reason 註明「疑似重複：<舊 ID>」。

### 家人領域與家族旅遊（來源設定）

- `md_table` 來源的 `include_any`：`[{欄位: [子字串]}, …]`，列不符合 `filter`、但符合任何一條（該條每個欄位至少含一個子字串）也收；`exclude` 最後判斷、優先。
- `md_table` 來源的 `item_rules`：`[{"col": 欄位, "contains": [子字串], "item": 項目}, …]`，照順序先中先贏，在 `item_map` 之前判斷（例如事件欄含「協助」「教家人用手機」就歸「幫助家人」）。
- `trips` 來源：讀旅程表（`path`，相對路徑以設定檔資料夾為準；欄位同 `trips.csv`），`filter`／`include_any` 挑出家族旅遊，每一趟一筆（項目預設「家族旅遊」，出處 `trips.csv#<trip_id>`）；沒有 `date_start` 的略過。`absorb_items`（預設 `["家人大事"]`）：落在旅程期間內、屬於這些項目的其他候選併進旅程那一筆，匯入時印「併進旅程 N 筆」。
- 人生成就卡出處是 `trips.csv#<id>` 時顯示「旅程：<名稱>」並可點到旅遊地圖；旅遊地圖上屬於該旅程的地點彈窗顯示「家人成就：<標題>」並可點到該領域分頁。旅遊領域的分數仍以地點計，不會重複算。

### 成就候選的日常流程（預設照 Opus 建議，只問拿不準的）

確認表多兩欄：`certainty`（把握度：高／低，Opus 判）和 `auto`（記著「自動」填進去的 decision）。流程：

1. `python scripts\check_achievements.py`（routine 每月呼叫；`--force` 立刻掃）：唯讀跑一次候選匯入，輸出一行，有新候選結束碼 10。掃描日記在 `private\achievement_scan_state.json`，只有掃完沒有新候選才記，未滿 30 天自動跳過。
2. `python scripts\import_achievements.py --write` 把新候選放進確認表。
3. Opus 判等級、`suggest`（y／n）和 `certainty`（規則不明、證據薄、前後標準難一致的標低），寫成 judgments.json（欄位多一個 `certainty`）。
4. `python scripts\apply_judgments.py judgments.json --auto-decide --write`：把握度高的自動填 decision（suggest＝y 填 y、n 填 n，`auto` 欄同步記下；寫入前備份 `*.before_auto.<時間戳>.csv`；`apply_achievements.py --write` 也會先備份 `achievements.before_apply.<時間戳>.csv`），低的留空。n 的留在確認表、之後不再冒出。`--auto-decide` 可以不帶判斷檔單獨用，`--default-certainty 高` 把握度空白的列視為高（套用既有批次用）。
5. `python scripts\apply_achievements.py --write` → `build_map.py` → `sync_kb.py --dry-run`，差異只有新增才 `--apply`。
6. 只有低把握度、decision 還空的才開題問使用者。使用者在 Excel 改 decision 以使用者為準（`auto` 欄跟 decision 不一致就不再算自動，重匯入也保留）。

不加 `--auto-decide` 就是舊流程：全部留空等使用者填。
