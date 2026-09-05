# 🏸 羽毛球會搶位報名系統 Badminton Club Grab-Registration

為「定時開搶、名額有限、先到先得」的球會活動設計的 H5 報名系統。
一個連結，微信 / WhatsApp / 瀏覽器都能打開，無需安裝任何 App。

## 功能 Features

- **定時開搶**：每場可單獨設定開放時間（提前 1–3 天），開搶前顯示倒鎖倒數，開搶瞬間先到先得
- **候補自動遞補**：名額滿了自動排候補；有人提前取消，候補按報名順序自動頂上
- **溫和不攔截**：每週第 3 場只提示不阻止；提前取消不處罰
- **匯出**：管理頁一鍵匯出「正選 + 候補 + 已付標記 + 本週第幾場」CSV；Google Sheets 模式還可同步到「匯出」分頁
- **極簡報名**：第一次選/輸入姓名後記住（瀏覽器本地），之後一鍵報名、一鍵取消
- **雙語**：關鍵步驟繁中 + English

## 技術棧

| 組件 | 選擇 | 費用 |
|---|---|---|
| 前端+後端 | Streamlit Community Cloud（`xxx.streamlit.app`） | ¥0 |
| 資料庫 | Google Sheets | ¥0 |

## 本地運行

```bash
pip install -r requirements.txt
streamlit run app.py
```

- 沒配置 Google 憑證時自動進入**本地模式**（資料存 `./data/*.csv`），方便先試玩
- 管理頁：<http://localhost:8501/admin>（本地模式預設密碼 `admin`）

## 自檢

```bash
python selfcheck.py          # 10 項核心邏輯測試（臨時資料夾，不污染專案）
python selfcheck.py --demo   # 本地生成演示資料，配合 streamlit run app.py 實測
```

## 部署

見 [DEPLOY.md](DEPLOY.md)，全程約 30 分鐘。

## 注意事項

- **重名**：報名以姓名為唯一標識，同名同姓的同學請約定加後綴（如「陳大文2」）
- **休眠**：Streamlit 免費版閒置會休眠，冷啟動約 30–60 秒；開搶前 10 分鐘先打開一次頁面即可（或見 DEPLOY.md 的保活方案）
- **資料**：正式環境全部存在你自己的 Google Sheet 裡，隨時可看可改可備份
