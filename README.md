# opendata-campus-mcp

**教育資源導航 MCP** — 以 [TWCampus](https://twcampus.org/) 作為目錄入口，路由至台灣官方教育平台，即時搜尋並讀取公開學習資源。

[![CI](https://github.com/trionnemesis/opendataCampus-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/trionnemesis/opendataCampus-MCP/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![MCP](https://img.shields.io/badge/MCP-FastMCP%203.x-7c3aed)
![License](https://img.shields.io/badge/license-MIT-green)

讓 LLM 不用自己亂猜網址、也不會把整個教育網站爬回來，而是經由一個**合規、可稽核**的導航層：先從本地目錄（必要時補 TWCampus）找到正確的官方平台 → 在平台上搜尋 → 讀取單一資源摘要。

---

## 目錄

- [特色](#特色)
- [架構](#架構)
- [運作原理](#運作原理)
- [安裝](#安裝)
- [在 MCP Client 中設定](#在-mcp-client-中設定)
- [MCP 工具](#mcp-工具)
- [瀏覽政策（合規護欄）](#瀏覽政策合規護欄)
- [內建教育平台目錄](#內建教育平台目錄)
- [測試](#測試)
- [來源 live 健康度](#來源-live-健康度)
- [專案結構](#專案結構)
- [開發與 SDD 規格](#開發與-sdd-規格)
- [擴充指南](#擴充指南)
- [限制與已知問題](#限制與已知問題)
- [合規聲明](#合規聲明)
- [授權](#授權)

---

## 特色

- **三段式導航**：`discover`（找平台）→ `browse`（搜資源）→ `read`（讀摘要），對應 LLM 真實的查找心智流程。
- **本地目錄優先**：內建 10 個已驗證的台灣官方教育平台，先查本地、不足才補 TWCampus，最小化對 TWCampus 的請求。
- **合規護欄寫死於 domain 層**：每域 3 req/min、每次請求最多 2 頁、不排程、不遞迴、不存全文、不繞過存取控制。
- **乾淨分層 + DI 邊界**：`contracts.py` 定義所有跨層 DTO / Protocol，新增平台或存取策略不需動到核心邏輯。
- **降級不中斷**：TWCampus 故障時靜默降級回本地目錄，工具永遠回傳結構化結果或明確的 `error` 物件。
- **SDD 驅動**：附 DDD 領域模型（`spec/erm.dbml`）與 5 組 BDD Gherkin feature，規格即文件。

---

## 架構

```
┌──────────────────────────────────────────────────────┐
│   MCP Client  (Claude Desktop / Claude Code / SDK)     │
└───────────────────────┬───────────────────────────────┘
                        │ stdio (MCP protocol)
┌───────────────────────▼───────────────────────────────┐
│  mcp_server/server.py    FastMCP · 3 tools · /healthz  │
│  mcp_server/service.py   EdBrowserService（協調層）     │
├────────────────────────────────────────────────────────┤
│  domain/   browser_policy（速率/頁面護欄）              │
│            source_router（關鍵字評分 + 階段過濾 + 路由）│
├────────────────────────────────────────────────────────┤
│  adapters/    twcampus（目錄）· web_search（搜尋/讀取） │
│               headless（Playwright 後備，預設停用）     │
│  repository/  source_cache（10 平台靜態目錄）           │
│  contracts.py  跨層 DTO / Enum / Error / Protocol       │
└───────────────────────┬────────────────────────────────┘
                        │ httpx GET + BeautifulSoup
                        ▼
        台灣官方教育平台（NTU OCW、教育大市集、因材網 …）
```

各層僅依賴 `contracts.py` 的型別，符合依賴反轉；`service.py` 以建構子注入 policy / router / adapter，方便測試以 mock 替換。

---

## 運作原理

```
使用者問題（例：「找台大資訊相關的開放課程」）
   │
   ▼
discover_education_sources    本地目錄評分排序 → 正分不足時補 TWCampus → 合併去重
   │                          回傳最相關的官方平台（含 official_url、適用階段）
   ▼
browse_education_source       httpx + BeautifulSoup 在指定平台搜尋
   │                          回傳 results[]（title / url / summary / 來源標記）
   ▼
read_education_resource       讀取單一資源頁面（摘要 ≤ 500 字元，不存全文）
   │
   ▼
回傳：標題、摘要、來源 URL、發行者
```

**設計取捨**：TWCampus 服務條款禁止大量下載，因此本專案將 TWCampus 定位為「**路由目錄**」而非資源倉庫 — 不儲存內容、不遞迴導航、不建立向量索引，所有抓取都由使用者即時觸發。

---

## 安裝

需求：Python 3.11+

```bash
git clone https://github.com/trionnemesis/opendataCampus-MCP.git
cd opendataCampus-MCP

# 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate

# 安裝（含開發依賴）
pip install -e ".[dev]"

# 可選：啟用 Playwright 後備支援（多數平台不需要）
pip install -e ".[headless]"
playwright install chromium
```

執行階段相依套件：`fastmcp>=0.2.0`、`httpx>=0.27`、`beautifulsoup4>=4.12`。

---

## 在 MCP Client 中設定

Server 以 **stdio** transport 啟動（`server.run()` 預設），可直接接入任何支援 MCP 的 client。請將下列路徑換成你的虛擬環境絕對路徑。

### Claude Desktop

編輯設定檔（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "opendata-campus": {
      "command": "/絕對路徑/opendataCampus-MCP/.venv/bin/opendata-campus-mcp"
    }
  }
}
```

若偏好以模組方式啟動：

```json
{
  "mcpServers": {
    "opendata-campus": {
      "command": "/絕對路徑/opendataCampus-MCP/.venv/bin/python",
      "args": ["-m", "opendata_campus_mcp.mcp_server"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add opendata-campus -- /絕對路徑/opendataCampus-MCP/.venv/bin/opendata-campus-mcp
```

### 手動啟動（除錯用）

```bash
opendata-campus-mcp
# 或
python -m opendata_campus_mcp.mcp_server
```

設定完成後，於 client 中可看到 `discover_education_sources`、`browse_education_source`、`read_education_resource` 三個工具。

---

## MCP 工具

### 1. `discover_education_sources`

從本地目錄（必要時補 TWCampus）找到相關官方教育平台。

| 參數 | 型別 | 說明 |
|------|------|------|
| `query` | `str` | 必填，查詢關鍵字 |
| `education_stage` | `str?` | 國小 / 國中 / 高中 / 大學 / 技職 / 全階段 |
| `subject` | `str?` | 科目關鍵字，命中平台分類可加權 |
| `max_sources` | `int` | 預設 3，上限 5 |

<details>
<summary>回傳範例</summary>

```json
[
  {
    "name": "臺大開放式課程 NTU OCW",
    "reason": "國立臺灣大學開放式課程，提供大學級影片講義",
    "official_url": "https://ocw.aca.ntu.edu.tw",
    "education_stages": ["大學"],
    "categories": ["開放課程", "大學課程", "影片", "講義"],
    "directory_source": "TWCampus",
    "access_strategy": "WEB_SEARCH"
  }
]
```
</details>

### 2. `browse_education_source`

在指定官方教育平台上搜尋學習資源。

| 參數 | 型別 | 說明 |
|------|------|------|
| `source` | `str` | 平台名稱（如「臺大開放式課程 NTU OCW」）或官方 URL |
| `query` | `str` | 搜尋關鍵字 |
| `max_results` | `int` | 預設 5，上限 5 |

<details>
<summary>回傳範例</summary>

```json
{
  "source": "臺大開放式課程 NTU OCW",
  "official_url": "https://ocw.aca.ntu.edu.tw",
  "query": "資訊",
  "total_returned": 5,
  "results": [
    {
      "title": "機動學",
      "url": "https://ocw.aca.ntu.edu.tw/courses/113S106",
      "summary": "…",
      "source_name": "臺大開放式課程 NTU OCW",
      "source_url": "https://ocw.aca.ntu.edu.tw",
      "education_stage": null,
      "subject": null
    }
  ]
}
```
</details>

### 3. `read_education_resource`

讀取單一公開教育資源頁面的摘要（不儲存全文）。

| 參數 | 型別 | 說明 |
|------|------|------|
| `url` | `str` | 資源頁面 URL |
| `extract` | `list[str]?` | 欲擷取欄位，預設全部六項 |

可擷取欄位：`title`、`summary`、`publisher`、`education_stage`、`subject`、`license`。

<details>
<summary>回傳範例</summary>

```json
{
  "url": "https://ocw.aca.ntu.edu.tw/courses/mooc0073",
  "title": "Operations Research (4): Capstone Project - 臺大開放式課程",
  "summary": "… 授課日期｜2025 年 10 月 … 開課單位：Information Management（資訊管理學系）…",
  "publisher": "NTU OpenCourseWare",
  "education_stage": null,
  "subject": null,
  "license": null
}
```
</details>

### 錯誤回傳

工具不會中斷對話，而是回傳結構化 `error` 物件：

| `error` | 觸發時機 | 出現工具 |
|---------|----------|----------|
| `rate_limited` | 超過每分鐘請求上限 | discover |
| `policy_violated` | 超過每次頁面上限 | discover |
| `source_unavailable` | 平台無法存取（網路錯誤 / 5xx） | browse, read |
| `login_required` | 資源需登入（401 / 403） | browse, read |

```json
{ "error": "source_unavailable", "url": "https://…", "message": "…" }
```

---

## 瀏覽政策（合規護欄）

護欄寫死於 [`domain/browser_policy.py`](src/opendata_campus_mcp/domain/browser_policy.py)，無法由請求參數放寬。

| 政策 | 值 |
|------|----|
| 每次請求最多頁數 | **2 頁** |
| 同域每分鐘請求上限 | **3 次**（滑動視窗，per-domain） |
| 排程爬取 | **停用** |
| 遞迴導航 | **停用** |
| 完整 HTML 儲存 | **停用** |
| 向量索引 | **停用** |
| 無頭瀏覽器（Playwright） | 預設 **停用**，需明確 `enabled=True` |
| 登入 / 繞過存取控制 | **永不嘗試** |

---

## 內建教育平台目錄

定義於 [`repository/source_cache.py`](src/opendata_campus_mcp/repository/source_cache.py)。

| 平台 | 適用階段 | 官方 URL |
|------|----------|----------|
| 教育大市集 | 國小 / 國中 / 高中 | https://market.cloud.edu.tw |
| 因材網 | 國小 / 國中 | https://adl.edu.tw |
| CIRN | 國小 / 國中 | https://cirn.moe.edu.tw |
| 教育部數位教學資源入口網 | 國小 / 國中 / 高中 / 大學 | https://resources.cloud.edu.tw |
| 全民英檢 GEPT | 國中 / 高中 / 大學 / 全階段 | https://www.gept.org.tw |
| 國立公共資訊圖書館 | 全階段 | https://www.nlpi.edu.tw |
| 教育部學力認證（大考中心） | 高中 | https://www.ceec.edu.tw |
| 均一教育平台 | 國小 / 國中 / 高中 | https://www.junyiacademy.org |
| 臺大開放式課程 NTU OCW | 大學 | https://ocw.aca.ntu.edu.tw |
| 國教院課程資源網 | 國小 / 國中 / 高中 | https://hh.ntue.edu.tw |

---

## 測試

```bash
# 單元測試（26 個；service / browser_policy / source_router）— CI 在此 gate
pytest tests/ -v

# 端對端整合測試（需網路，實際抓取 NTU OCW）
python scripts/integration_e2e.py

# 全來源 live smoke test（需網路，對 10 個內建來源各跑一次 browse 並回報健康度）
python scripts/smoke_sources.py
```

`scripts/smoke_sources.py` 是維護者用的 live 診斷工具（**非** CI gate）：對每個內建來源跑一次 `browse`，依連線結果標記 ✅ OK / ⚠️ EMPTY / 🔒 LOGIN / ❌ UNAVAILABLE，快速看出哪些來源的搜尋 / 解析器仍正常。最近實測見 [來源 live 健康度](#來源-live-健康度)。

整合測試實際抓取結果（真實遠端，非快取）：

```
課程名稱 : Operations Research (4): Capstone Project
          作業研究（四）：專題實作
開課單位 : Information Management（資訊管理學系）
授課日期 : 2025 年 10 月
授課教師 : Ling-Chieh Kung（孔令傑）
平台     : 臺大開放式課程 NTU OCW
URL      : https://ocw.aca.ntu.edu.tw/courses/mooc0073
```

> 抓取真實性驗證：對同一頁多次 `read`，頁面「本月點閱」計數隨抓取單調遞增，確認為即時遠端 GET 而非靜態快取或靜默降級。

---

## 來源 live 健康度

最近一次 `scripts/smoke_sources.py` 實測（Python 3.14 + 較新 OpenSSL 環境）：

| 來源 | 狀態 | 說明 |
|------|------|------|
| 全民英檢 GEPT | ✅ OK | browse 回傳 5 筆 |
| 均一教育平台 | ✅ OK | browse 回傳 5 筆 |
| 臺大開放式課程 NTU OCW | ✅ OK | browse 回傳 5 筆 |
| 因材網 | 🔶 憑證相容性 | 網站正常（`curl` 302），Python OpenSSL 因憑證缺 Subject Key Identifier 而拒絕 |
| 國立公共資訊圖書館 | 🔶 憑證相容性 | 網站正常（`curl` 200），同上 |
| 教育部學力認證 | 🔶 憑證相容性 | 網站正常（`curl` 200），同上 |
| 教育大市集 | ⛔ 連線受阻 | TLS 握手 send failure（疑似阻擋非瀏覽器） |
| CIRN | ⛔ 連線受阻 | 連線逾時 |
| 教育部數位教學資源入口網 | ❌ DNS 失效 | `resources.cloud.edu.tw` 無法解析 |
| 國教院課程資源網 | ❌ DNS 失效 | `hh.ntue.edu.tw` 無法解析 |

- **🔶 憑證相容性**：網站本身存活，僅因台灣 .edu.tw 政府憑證缺少 Subject Key Identifier、在較新 OpenSSL 下驗證失敗；於使用系統憑證庫或較舊 OpenSSL 的環境通常可正常抓取。
- **❌ DNS 失效**：[`source_cache.py`](src/opendata_campus_mcp/repository/source_cache.py) 中這兩筆 `official_url` 已無法解析，需更新為現行網址。
- 此表為單一環境快照，僅供參考；請以你自己環境執行 `smoke_sources.py` 的結果為準。

---

## 專案結構

```
opendataCampus-MCP/
├── .github/workflows/
│   └── ci.yml                      # GitHub Actions：離線單元測試 gate
├── spec/
│   ├── erm.dbml                    # DDD 領域模型（DBML）
│   └── features/                   # BDD Gherkin 規格
│       ├── discover-sources.feature
│       ├── browse-source.feature
│       ├── read-resource.feature
│       ├── browser-policy.feature
│       └── source-routing.feature
├── src/opendata_campus_mcp/
│   ├── contracts.py                # 跨層 DTO / Enum / Error / Protocol
│   ├── domain/
│   │   ├── browser_policy.py       # 速率限制 + 頁面限制護欄
│   │   └── source_router.py        # 關鍵字評分 + 階段過濾 + 策略路由
│   ├── adapters/
│   │   ├── twcampus.py             # TWCampus 目錄導航（httpx）
│   │   ├── web_search.py           # 官方平台搜尋 / 讀取（httpx + BS4）
│   │   └── headless.py             # Playwright 後備（預設停用）
│   ├── repository/
│   │   └── source_cache.py         # 10 個已知台灣教育平台目錄
│   └── mcp_server/
│       ├── __main__.py             # python -m 進入點
│       ├── service.py              # EdBrowserService（協調層）
│       └── server.py               # FastMCP 工具定義
├── tests/
│   ├── test_browser_policy.py
│   ├── test_source_router.py
│   └── test_service.py
├── scripts/
│   ├── integration_e2e.py          # 端對端整合測試（NTU OCW）
│   └── smoke_sources.py            # 全來源 live 健康度 smoke test
└── pyproject.toml
```

---

## 開發與 SDD 規格

本專案採規格驅動開發（Spec-Driven Development）：

- **DDD 領域模型** — [`spec/erm.dbml`](spec/erm.dbml)：`EducationSource`（Aggregate Root）、`SearchResult` / `ResourceDetail`（Value Object）等實體關係。
- **BDD 行為規格** — [`spec/features/`](spec/features)：5 組 Gherkin feature 對應三個工具與兩條核心不變量（瀏覽政策、來源路由），可作為驗收條件與測試基準。

核心型別集中於 [`contracts.py`](src/opendata_campus_mcp/contracts.py)，遵循「型別即文件」；新增功能前建議先更新對應 `.feature`。

---

## 擴充指南

| 需求 | 做法 |
|------|------|
| **新增教育平台** | 在 [`source_cache.py`](src/opendata_campus_mcp/repository/source_cache.py) 的 `_CATALOG` 加一筆 `EducationSource`，無需改動其他程式碼。 |
| **新增存取策略** | 在 `contracts.AccessStrategy` 加一個 enum 值（含 `priority`），並實作對應 adapter（符合 `DirectoryAdapter` / `BrowseAdapter` Protocol）。 |
| **調整路由優先序** | 修改 `AccessStrategy.priority` 與 `source_router.PRIORITY_ORDER`。 |

路由優先序：`OFFICIAL_API`(0) > `OPEN_DATA`(1) > `WEB_SEARCH`(2) > `TWCAMPUS_DIRECTORY`(3) > `HEADLESS_BROWSER`(4)。

---

## 限制與已知問題

誠實標註目前邊界，供使用前評估：

- **各來源 live 可用性不一**：實測 10 個內建來源中 3 個可正常 browse（GEPT、均一、NTU OCW），3 個憑證相容性、2 個連線受阻、2 個 DNS 失效 — 詳見 [來源 live 健康度](#來源-live-健康度)。可用性會隨各站改版與執行環境而變動。
- **`read` 的 `education_stage` / `subject` 目前固定回傳 `null`**：[`web_search.py`](src/opendata_campus_mcp/adapters/web_search.py) 尚未實作這兩個欄位的擷取邏輯。
- **`discover` 的 TWCampus 降級是靜默的**：TWCampus 任何故障（含潛在程式錯誤）都會被吞為 `log.info` 後退回本地目錄，正常路徑與降級路徑對使用者輸出不易區分。
- **NTU OCW 的 `browse` 為首頁列表而非關鍵字搜尋**：因目標站 WAF 限制，`query` 實際未對課程做過濾，回傳的是首頁近期課程清單，語意與「搜尋」略有落差。
- **無頭瀏覽器後備預設停用**：需 JavaScript 渲染的平台在未啟用 Playwright 時可能取不到內容。

---

## 合規聲明

本工具僅存取**公開**教育資源，遵守來源網站服務條款：不執行大量 / 排程下載、不遞迴爬取、不儲存完整內容、不嘗試登入或繞過任何存取控制。TWCampus 僅作為路由目錄使用。所有抓取均由使用者即時查詢觸發。

---

## 授權

[MIT](LICENSE)
