# 架構與設計

> ← 回到 [README](../README.md)

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

- **DDD 領域模型** — [`spec/erm.dbml`](../spec/erm.dbml)：`EducationSource`（Aggregate Root）、`SearchResult` / `ResourceDetail`（Value Object）等實體關係。
- **BDD 行為規格** — [`spec/features/`](../spec/features)：5 組 Gherkin feature 對應三個工具與兩條核心不變量（瀏覽政策、來源路由），可作為驗收條件與測試基準。

核心型別集中於 [`contracts.py`](../src/opendata_campus_mcp/contracts.py)，遵循「型別即文件」；新增功能前建議先更新對應 `.feature`。

---

## 擴充指南

| 需求 | 做法 |
|------|------|
| **新增教育平台** | 在 [`source_cache.py`](../src/opendata_campus_mcp/repository/source_cache.py) 的 `_CATALOG` 加一筆 `EducationSource`，無需改動其他程式碼。 |
| **新增存取策略** | 在 `contracts.AccessStrategy` 加一個 enum 值（含 `priority`），並實作對應 adapter（符合 `DirectoryAdapter` / `BrowseAdapter` Protocol）。 |
| **調整路由優先序** | 修改 `AccessStrategy.priority` 與 `source_router.PRIORITY_ORDER`。 |

路由優先序：`OFFICIAL_API`(0) > `OPEN_DATA`(1) > `WEB_SEARCH`(2) > `TWCAMPUS_DIRECTORY`(3) > `HEADLESS_BROWSER`(4)。
