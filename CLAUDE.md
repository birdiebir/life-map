# life-map：人生成就地圖

## 開工前先讀
1. `README.md`：怎麼跑、資料格式、資料來源與授權。
2. `docs\規格書_第一階段旅遊地圖.md`：範圍、資料模型、里程碑。
3. `docs\開發日誌.md` 最上面一段：做到哪、下一步。

## 規則
- 個人足跡只放 `private\`（不進 git）；程式一律透過 `paths.py` 取路徑。`private.example\` 只放假資料。
- `visits.csv` 只存地點 ID，不存座標；時間軸原始檔（推得出住家位置）只放 `private\raw\`，不寫進筆記庫、開發日誌、commit 訊息。
- 地點判斷全部離線，不呼叫外部地理編碼 API。
- 自動推定的足跡一律先進 `pending.csv`／`confirmed=false`，使用者確認後才算。
- 文件與測試只用虛構的人名、地名、公司名；不放真實姓名、email、本機路徑。
- 每次工作階段結束前，在 `docs\開發日誌.md` 最上面補 `## YYYY-MM-DD`（只寫可公開內容）。
- commit 前閘門：`python guard\scan.py --staged`（`python guard\install_git_hooks.py` 安裝後自動跑）；名單檔 `private\blocklist.txt` 不進 git。
