# 部署指南（Streamlit Cloud + Google Sheets，全程免費）

整個流程約 30 分鐘，做一次以後永久可用。

## 0. 前置

- 一個 GitHub 賬號
- 一個 Google 賬號

## 1. 建立 Google Sheet（資料庫）

1. 打開 <https://sheets.new> 建一個空白表格
2. 從瀏覽器地址欄複製表格 ID：
   `https://docs.google.com/spreadsheets/d/`**`這一串就是SHEET_ID`**`/edit`
3. 不用建分頁——應用首次運行會自動創建 `events`、`registrations`、`members` 三個分頁

## 2. 建立服務賬號（讓應用能讀寫這張表）

1. 打開 <https://console.cloud.google.com> → 頂部新建項目（名字隨意，如 `badminton-club`）
2. 左側菜單「API 和服務 → 庫」→ 搜索並啟用 **Google Sheets API**
3. 「API 和服務 → 憑據」→「創建憑據 → 服務賬號」→ 名字隨意，一路跳過角色，完成
4. 點進該服務賬號 →「密鑰」→「添加密鑰 → JSON」→ 自動下載一個 JSON 文件
5. **共享表格**：回到你的 Google Sheet →「共享」→ 把 JSON 裡的
   `client_email`（形如 `xxx@badminton-club.iam.gserviceaccount.com`）
   添加為**編輯者**

## 3. 代碼上傳 GitHub

```bash
cd badminton-club-registration
git init
git add .
git commit -m "v1: badminton club grab-registration"
# 在 github.com 上新建一個私有倉庫後：
git remote add origin https://github.com/你的用戶名/倉庫名.git
git push -u origin main
```

> 不想用命令行的話：GitHub 網頁端「Upload files」把文件全部拖進去也行
> （注意 `.streamlit/secrets.toml` 不要上傳，只上傳 `secrets.toml.example`）

## 4. 部署到 Streamlit Cloud

1. 打開 <https://share.streamlit.io> → 用 GitHub 登錄
2. 「Create app」→ 選倉庫 / 分支 `main` / 主文件 `app.py` → Deploy
3. 部署完成會得到一個 `https://你的應用名.streamlit.app` 的公開連結

## 5. 配置 Secrets（最後一步，關鍵）

1. 應用頁面右下角「Manage app」→「Settings」→「Secrets」
2. 打開 `secrets.toml.example`，照著填：把下載的服務賬號 JSON 裡的字段逐個複製進對應位置
3. 粘貼進 Secrets 框，保存 → 應用自動重啟

**`private_key` 注意**：保持一整行，`-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n` 中的 `\n` 原樣保留（JSON 文件裡就是這種格式，直接複製即可）。

## 6. 首次使用

1. 打開 `https://你的應用名.streamlit.app/admin`，輸入 `ADMIN_PASSWORD` 登入
2. 「會員 Members」→ 粘貼會員名單（每行一個姓名）→ 保存
3. 「場次 Sessions」→「快速建立本週場次」：選星期、名額（週一 28 / 其他 24）、提前幾天開放、開放時刻 → 建立
4. 回首頁用一個測試姓名試搶一場，確認流程通暢

## 7. 上線前測試清單

- [ ] 建一個名額=2 的測試場次發到群裡
- [ ] 3 個人同時搶：前 2 個正選，第 3 個進候補
- [ ] 其中 1 個正選取消：候補自動變正選
- [ ] 手機微信裡打開連結操作一遍
- [ ] 管理頁匯出 CSV、標記「已付」各試一次
- [ ] 全部通過後刪掉測試場次，建立正式場次

## 8. 保活（避免開搶瞬間撞上冷啟動）

免費版應用閒置會休眠，喚醒需 30–60 秒。兩個辦法：

- **方案 A（最簡單）**：開搶前 10 分鐘，你自己（或任何群友）打開一次連結
- **方案 B（自動）**：<https://cron-job.org> 註冊免費賬號 → 新建任務 → 每 20 分鐘 GET 你的應用首頁

## 常見問題

| 現象 | 原因 / 解法 |
|---|---|
| 打開就報 403 | Sheet 沒共享給服務賬號 → 回到第 2 步第 5 小步 |
| 報 private_key 相關錯誤 | `\n` 被破壞 → 重新從 JSON 整段複製 |
| 429 / quota 錯誤 | 讀取超配額 → 應用已內置 3 秒全站緩存，正常操作不會觸頂；若出現，等 1 分鐘自恢復 |
| 改了 secrets 沒生效 | 「Manage app」→ 三點菜單 → Reboot |
| 開搶瞬間卡 30 秒 | 冷啟動 → 見第 8 節保活 |
