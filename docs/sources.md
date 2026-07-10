# 教育平台來源

> ← 回到 [README](../README.md)

## 內建教育平台目錄

定義於 [`repository/source_cache.py`](../src/opendata_campus_mcp/repository/source_cache.py)。

| 平台 | 適用階段 | 官方 URL |
|------|----------|----------|
| 教育大市集 | 國小 / 國中 / 高中 | https://market.cloud.edu.tw（`OFFICIAL_API`，需 key） |
| 因材網 | 國小 / 國中 | https://adl.edu.tw |
| CIRN | 國小 / 國中 | https://cirn.k12ea.gov.tw |
| 教育部數位教學資源入口網 | 國小 / 國中 / 高中 / 大學 | https://cloud.edu.tw |
| 全民英檢 GEPT | 國中 / 高中 / 大學 / 全階段 | https://www.gept.org.tw |
| 國立公共資訊圖書館 | 全階段 | https://www.nlpi.edu.tw |
| 大學入學考試中心 CEEC | 高中 | https://www.ceec.edu.tw |
| 均一教育平台 | 國小 / 國中 / 高中 | https://www.junyiacademy.org |
| 國教院課程資源網 | 國小 / 國中 / 高中 | https://www.naer.edu.tw |
| 政府資料開放平臺 | 全階段（統計 / 名錄） | https://data.gov.tw（`OPEN_DATA`） |

---

## 來源 live 健康度

最近一次 `scripts/smoke_sources.py` 實測（2026-07-11，**無 key 情境**：未設 `EDUMARKET_API_KEY`）：

| 來源 | 狀態 | 說明 |
|------|------|------|
| 因材網 | ✅ OK | browse 回傳 5 筆 |
| 教育部數位教學資源入口網 | ✅ OK | browse 回傳 1 筆 |
| 全民英檢 GEPT | ✅ OK | browse 回傳 5 筆 |
| 國立公共資訊圖書館 | ✅ OK | browse 回傳 5 筆 |
| 大學入學考試中心 CEEC | ✅ OK | browse 回傳 5 筆 |
| 均一教育平台 | ✅ OK | browse 回傳 5 筆 |
| 國教院課程資源網 | ✅ OK | browse 回傳 5 筆（前次快照曾連線中斷，live 狀態不穩） |
| 政府資料開放平臺 | ✅ OK | `OPEN_DATA` browse 回傳 3 筆（本地 catalog，不打 API） |
| 教育大市集 | ❌ 未設定 key | 走 OFFICIAL_API adapter，於 HTTP request 前回 `EDUMARKET_API_KEY not configured` |
| CIRN | ⚠️ EMPTY | canonical host 連線成功，但通用 parser 對本次查詢未解析出結果 |

> OK=8 / EMPTY=1 / FAIL=1（10 來源）。

- **教育大市集**：未設定 key 時明確回 `source_unavailable`，不再降級為已知 404 的 web search；**設 `EDUMARKET_API_KEY` 後 browse 走官方 v2 API**（見 [安裝與設定](setup.md#教育大市集官方-api-key選用)）。
- 此表為單一環境、無 key 情境的快照，僅供參考；請以你自己環境執行 `smoke_sources.py` 的結果為準。

---

## 政府資料開放平臺（`OPEN_DATA`）

[政府資料開放平臺](https://data.gov.tw)（data.gov.tw）是 `OPEN_DATA` 存取策略的第一個來源，透過既有 `browse_education_source` / `read_education_resource` 工具存取（service 依 `access_strategy` 分派到 `OpenDataApiAdapter`，**非新增 MCP 工具**）。dataset 清單為手動驗證的本地 catalog，定義於 [`repository/opendata_catalog.py`](../src/opendata_campus_mcp/repository/opendata_catalog.py)，與平台層的 `source_cache.py` 分離。

| 項目 | 說明 |
|------|------|
| **browse** | 在本地 catalog 做關鍵字過濾（**不打 API**，省請求）→ 回傳 dataset 連結（`url` 形如 `https://data.gov.tw/dataset/{id}`，含 `education_stage` / `subject`） |
| **read** | 抽 dataset id → `GET https://data.gov.tw/api/v2/rest/dataset/{id}` → 回傳 dict，**額外含 `resources` 陣列**（每筆 `{format, download_url}` 指向 stats.moe.gov.tw 的 CSV / JSON 實際下載點）+ `license` 解碼 |
| **誠實定位** | 8 dataset 中 **6 筆教育統計**（學生數 / 教師數 / 比率 / 概況）+ **2 筆名錄**（校院名錄 / 高中職名錄）；屬**統計 / 名錄類開放資料，非教材或題庫** |
| 授權 | 皆教育部、[政府資料開放授權條款-第1版 (OGDL v1.0)](https://data.gov.tw)，附 CSV / JSON 下載點 |

8 個已驗證 dataset：

| dataset id | 名稱 | 類別 |
|------------|------|------|
| 6091 | 大專校院名錄 | 名錄 |
| 6089 | 一般高級中等學校名錄 | 名錄 |
| 6288 | 大專校院圖書館統計 | 統計 |
| 9624 | 大專校院各校科系別專任教師數 | 統計 |
| 40121 | 各級學校縣市別學生人數 | 統計 |
| 31437 | 各級學校概況 | 統計 |
| 31438 | 各級學校年齡別學生人數 | 統計 |
| 40118 | 各級學校學生人數占年底人口比率 | 統計 |

---

## CEEC 考古題垂直（`search_exam_questions`）

[`search_exam_questions`](tools.md#4-search_exam_questions) 是獨立於三段式導航的考古題垂直，由 [`adapters/ceec_exam.py`](../src/opendata_campus_mcp/adapters/ceec_exam.py) 解析大考中心（CEEC）的 server-rendered listing 表格。

| 項目 | 說明 |
|------|------|
| 涵蓋範圍 | CEEC **學測** + **分科測驗**（各對應一個 `xsmsid` listing）；國中會考因 `robots.txt` Disallow 不納入，統測列後續 |
| listing 端點 | `GET /xmfile?xsmsid={XSMSID}&page={N}`，每頁約 **10 筆** |
| 檔案格式 | `download_url` 多為 **PDF**，部分另提供 **`.docx`**；一列多檔（試題 / 答案 / 答題卷 / 評分原則）攤平成多筆 |
| 分頁上限 | 受瀏覽政策約束，單次最多掃 **2 頁**（≈ 最新 20 筆）；只回連結字串，不下載全文 |
