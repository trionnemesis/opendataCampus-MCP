# opendata-campus-mcp

**教育資源導航 MCP** — 以 [TWCampus](https://twcampus.org/) 作為目錄入口，路由至台灣官方教育平台，即時搜尋並讀取公開學習資源。

[![CI](https://github.com/trionnemesis/opendataCampus-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/trionnemesis/opendataCampus-MCP/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![MCP](https://img.shields.io/badge/MCP-FastMCP%203.x-7c3aed)
![License](https://img.shields.io/badge/license-MIT-green)

讓 LLM 不用自己亂猜網址、也不會把整個教育網站爬回來，而是經由一個**合規、可稽核**的導航層：先從本地目錄（必要時補 TWCampus）找到正確的官方平台 → 在平台上搜尋 → 讀取單一資源摘要。

---

## 📖 文件導覽

完整內容依主題拆分於 [`docs/`](docs/)，依需求檢索：

| 文件 | 內容 |
|------|------|
| [安裝與設定](docs/setup.md) | 安裝步驟、在 Claude Desktop / Claude Code 中設定、測試指令 |
| [MCP 工具 API](docs/tools.md) | `discover` / `browse` / `read` 三個工具的參數、回傳範例、錯誤回傳 |
| [架構與設計](docs/architecture.md) | 分層架構圖、運作原理、專案結構、SDD 規格、擴充指南 |
| [教育平台來源](docs/sources.md) | 內建 10 個平台目錄、來源 live 健康度實測 |
| [合規與限制](docs/compliance.md) | 瀏覽政策護欄、已知問題、合規聲明 |
| [無頭瀏覽策略](docs/headless.md) | Playwright 後備取捨、Browserbase / 雲端無頭瀏覽服務評估 |

---

## 特色

- **三段式導航**：`discover`（找平台）→ `browse`（搜資源）→ `read`（讀摘要），對應 LLM 真實的查找心智流程。
- **本地目錄優先**：內建 10 個已驗證的台灣官方教育平台，先查本地、不足才補 TWCampus，最小化對 TWCampus 的請求。
- **合規護欄寫死於 domain 層**：每域 3 req/min、每次請求最多 2 頁、不排程、不遞迴、不存全文、不繞過存取控制。
- **乾淨分層 + DI 邊界**：`contracts.py` 定義所有跨層 DTO / Protocol，新增平台或存取策略不需動到核心邏輯。
- **降級不中斷**：TWCampus 故障時靜默降級回本地目錄，工具永遠回傳結構化結果或明確的 `error` 物件。
- **SDD 驅動**：附 DDD 領域模型（`spec/erm.dbml`）與 5 組 BDD Gherkin feature，規格即文件。

---

## 快速開始

需求：Python 3.11+

```bash
git clone https://github.com/trionnemesis/opendataCampus-MCP.git
cd opendataCampus-MCP
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

接入 Claude Code：

```bash
claude mcp add opendata-campus -- /絕對路徑/opendataCampus-MCP/.venv/bin/opendata-campus-mcp
```

> 其他 client 設定、Playwright 後備安裝、測試指令見 [安裝與設定](docs/setup.md)。

---

## MCP 工具

| 工具 | 用途 |
|------|------|
| `discover_education_sources(query, education_stage?, subject?, max_sources=3)` | 找到相關官方教育平台 |
| `browse_education_source(source, query, max_results=5)` | 在指定平台搜尋學習資源 |
| `read_education_resource(url, extract?)` | 讀取單一資源頁面摘要 |

> 參數細節、回傳範例與錯誤回傳見 [MCP 工具 API](docs/tools.md)。

---

## 合規護欄

護欄寫死於 [`domain/browser_policy.py`](src/opendata_campus_mcp/domain/browser_policy.py)，無法由請求參數放寬：

| 政策 | 值 |
|------|----|
| 每次請求最多頁數 | **2 頁** |
| 同域每分鐘請求上限 | **3 次**（滑動視窗，per-domain） |
| 排程爬取 / 遞迴導航 / 全文儲存 / 向量索引 | **全部停用** |
| 無頭瀏覽器（Playwright） | 預設 **停用**，需明確 `enabled=True` |
| 登入 / 繞過存取控制 | **永不嘗試** |

本工具僅存取**公開**教育資源並遵守來源服務條款；TWCampus 僅作路由目錄，所有抓取均由使用者即時查詢觸發。完整聲明與已知限制見 [合規與限制](docs/compliance.md)。

---

## 授權

[MIT](LICENSE)
