# opendata-campus-mcp

**教育資源導航 MCP** — 以 [TWCampus](https://twcampus.org/) 作為目錄入口，路由至台灣官方教育平台，即時搜尋並讀取公開學習資源。

## 架構概覽

```
使用者問題
   ↓
discover_education_sources   ← 本地目錄優先 → 不足時補 TWCampus
   ↓
browse_education_source      ← httpx + BeautifulSoup 搜尋官方平台
   ↓
read_education_resource      ← 讀取單一資源摘要（≤500 字元，不存全文）
   ↓
回傳：標題、摘要、來源 URL、發行者
```

## MCP 工具

### `discover_education_sources`

從 TWCampus 目錄找到相關官方教育平台。

```json
{
  "query": "資訊管理 大學",
  "education_stage": "大學",
  "max_sources": 3
}
```

回傳每筆包含 `name`、`official_url`、`categories`、`education_stages`、`directory_source`。

### `browse_education_source`

在指定官方教育平台上搜尋學習資源。

```json
{
  "source": "臺大開放式課程 NTU OCW",
  "query": "資訊",
  "max_results": 5
}
```

回傳 `results[]`，每筆含 `title`、`url`、`summary`、`source_name`、`source_url`。

### `read_education_resource`

讀取單一公開教育資源頁面的摘要資訊。

```json
{
  "url": "https://ocw.aca.ntu.edu.tw/courses/mooc0073",
  "extract": ["title", "summary", "publisher", "education_stage", "subject", "license"]
}
```

## 瀏覽政策（TWCampus 條款合規）

| 政策 | 值 |
|------|----|
| 每次請求最多頁數 | 2 頁 |
| TWCampus 每分鐘請求上限 | 3 次 |
| 排程爬取 | **停用** |
| 遞迴導航 | **停用** |
| 完整 HTML 儲存 | **停用** |
| 向量索引 | **停用** |
| 無頭瀏覽器（Playwright）| 預設 **停用**，需明確 `enabled=True` |

## 安裝

```bash
# 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate

# 安裝（含開發依賴）
pip install -e ".[dev]"

# 可選：啟用 Playwright 後備支援
pip install -e ".[headless]"
playwright install chromium
```

## 執行 MCP Server

```bash
opendata-campus-mcp
```

或直接以模組執行：

```bash
python -m opendata_campus_mcp.mcp_server
```

## 測試

```bash
# 單元測試（26 個）
pytest tests/ -v

# 端對端整合測試（需網路，實際抓取 NTU OCW）
python scripts/integration_e2e.py
```

整合測試驗證結果（真實抓取）：

```
課程名稱 : Operations Research (4): Capstone Project
          作業研究（四）：專題實作
開課單位 : Information Management（資訊管理學系）
授課日期 : 2025 年 10 月
授課教師 : Ling-Chieh Kung（孔令傑）
平台     : 臺大開放式課程 NTU OCW
URL      : https://ocw.aca.ntu.edu.tw/courses/mooc0073
```

## 專案結構

```
opendataCampus-MCP/
├── spec/
│   ├── erm.dbml                    # DDD 領域模型（DBML）
│   └── features/                   # BDD Gherkin 規格
│       ├── discover-sources.feature
│       ├── browse-source.feature
│       ├── read-resource.feature
│       ├── browser-policy.feature
│       └── source-routing.feature
├── src/opendata_campus_mcp/
│   ├── contracts.py                # 跨層 DTO / Enum / Protocol
│   ├── domain/
│   │   ├── browser_policy.py       # 速率限制 + 頁面限制護欄
│   │   └── source_router.py        # 關鍵字評分 + 策略路由
│   ├── adapters/
│   │   ├── twcampus.py             # TWCampus 目錄導航（httpx）
│   │   ├── web_search.py           # 官方平台搜尋（httpx + BS4）
│   │   └── headless.py             # Playwright 後備（預設停用）
│   ├── repository/
│   │   └── source_cache.py         # 10 個已知台灣教育平台目錄
│   └── mcp_server/
│       ├── service.py              # EdBrowserService（協調層）
│       └── server.py               # FastMCP 工具定義
├── tests/
│   ├── test_browser_policy.py
│   ├── test_source_router.py
│   └── test_service.py
├── scripts/
│   └── integration_e2e.py          # 端對端整合測試
└── pyproject.toml
```

## 內建教育平台目錄

| 平台 | 適用階段 | 官方 URL |
|------|----------|----------|
| 教育大市集 | 國小/國中/高中 | https://market.cloud.edu.tw |
| 因材網 | 國小/國中 | https://adl.edu.tw |
| CIRN | 國小/國中 | https://cirn.moe.edu.tw |
| 教育部數位教學資源入口網 | 全階段 | https://resources.cloud.edu.tw |
| 全民英檢 GEPT | 全階段 | https://www.gept.org.tw |
| 國立公共資訊圖書館 | 全階段 | https://www.nlpi.edu.tw |
| 教育部學力認證 CEEC | 高中 | https://www.ceec.edu.tw |
| 均一教育平台 | 國小/國中/高中 | https://www.junyiacademy.org |
| 臺大開放式課程 NTU OCW | 大學 | https://ocw.aca.ntu.edu.tw |
| 國教院課程資源網 | 國小/國中/高中 | https://hh.ntue.edu.tw |

## 新增平台

在 [`src/opendata_campus_mcp/repository/source_cache.py`](src/opendata_campus_mcp/repository/source_cache.py) 的 `_CATALOG` 加一筆 `EducationSource` 即可，不需修改其他程式碼。

## 授權

MIT
