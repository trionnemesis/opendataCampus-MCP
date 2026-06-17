# 教育平台來源

> ← 回到 [README](../README.md)

## 內建教育平台目錄

定義於 [`repository/source_cache.py`](../src/opendata_campus_mcp/repository/source_cache.py)。

| 平台 | 適用階段 | 官方 URL |
|------|----------|----------|
| 教育大市集 | 國小 / 國中 / 高中 | https://market.cloud.edu.tw（`OFFICIAL_API`，需 key） |
| 因材網 | 國小 / 國中 | https://adl.edu.tw |
| CIRN | 國小 / 國中 | https://cirn.moe.edu.tw |
| 教育部數位教學資源入口網 | 國小 / 國中 / 高中 / 大學 | https://cloud.edu.tw |
| 全民英檢 GEPT | 國中 / 高中 / 大學 / 全階段 | https://www.gept.org.tw |
| 國立公共資訊圖書館 | 全階段 | https://www.nlpi.edu.tw |
| 大學入學考試中心 CEEC | 高中 | https://www.ceec.edu.tw |
| 均一教育平台 | 國小 / 國中 / 高中 | https://www.junyiacademy.org |
| 國教院課程資源網 | 國小 / 國中 / 高中 | https://www.naer.edu.tw |

---

## 來源 live 健康度

最近一次 `scripts/smoke_sources.py` 實測（2026-06，**無 key 情境**：未設 `EDUMARKET_API_KEY`）：

| 來源 | 狀態 | 說明 |
|------|------|------|
| 因材網 | ✅ OK | browse 回傳 5 筆 |
| 教育部數位教學資源入口網 | ✅ OK | browse 回傳 1 筆 |
| 全民英檢 GEPT | ✅ OK | browse 回傳 5 筆 |
| 國立公共資訊圖書館 | ✅ OK | browse 回傳 5 筆 |
| 大學入學考試中心 CEEC | ✅ OK | browse 回傳 5 筆 |
| 均一教育平台 | ✅ OK | browse 回傳 5 筆 |
| 教育大市集 | ❌ 無 key 降級 | 未設 `EDUMARKET_API_KEY` 時走 web_search 降級，該搜尋頁回 HTTP 404 |
| CIRN | ❌ 憑證不符 | `cirn.k12ea.gov.tw` 憑證名稱與輸入網域不符 |
| 國教院課程資源網 | ❌ 連線中斷 | Server disconnected without sending a response |

- **教育大市集**：上表為無 key 快照故降級；**設 `EDUMARKET_API_KEY` 後 browse 走官方 v2 API 即正常**（見 [安裝與設定](setup.md#教育大市集官方-api-key選用)）。
- 此表為單一環境、無 key 情境的快照，僅供參考；請以你自己環境執行 `smoke_sources.py` 的結果為準。

---

## CEEC 考古題垂直（`search_exam_questions`）

[`search_exam_questions`](tools.md#4-search_exam_questions) 是獨立於三段式導航的考古題垂直，由 [`adapters/ceec_exam.py`](../src/opendata_campus_mcp/adapters/ceec_exam.py) 解析大考中心（CEEC）的 server-rendered listing 表格。

| 項目 | 說明 |
|------|------|
| 涵蓋範圍 | CEEC **學測** + **分科測驗**（各對應一個 `xsmsid` listing）；國中會考因 `robots.txt` Disallow 不納入，統測列後續 |
| listing 端點 | `GET /xmfile?xsmsid={XSMSID}&page={N}`，每頁約 **10 筆** |
| 檔案格式 | `download_url` 多為 **PDF**，部分另提供 **`.docx`**；一列多檔（試題 / 答案 / 答題卷 / 評分原則）攤平成多筆 |
| 分頁上限 | 受瀏覽政策約束，單次最多掃 **2 頁**（≈ 最新 20 筆）；只回連結字串，不下載全文 |
