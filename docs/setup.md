# 安裝與設定

> ← 回到 [README](../README.md)

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

執行階段相依套件：`fastmcp>=0.2.0`、`httpx>=0.27`、`beautifulsoup4>=4.12`、`truststore`（用系統憑證庫解決台灣 .edu.tw 政府憑證在較新 OpenSSL 下的驗證問題）。

> 是否需要 `[headless]`？多數內建平台為 server-rendered，`httpx + BeautifulSoup` 已足夠。詳見 [無頭瀏覽策略](headless.md)。

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

設定完成後，於 client 中可看到 `discover_education_sources`、`browse_education_source`、`read_education_resource`、`search_exam_questions` 四個工具。完整 API 見 [MCP 工具](tools.md)。

---

## 教育大市集官方 API Key（選用）

教育大市集為 `OFFICIAL_API` 來源。提供 `EDUMARKET_API_KEY` 後，browse 會走官方 v2 REST API 並回傳結構化的學制 / 領域欄位；**無 key 時回傳 `source_unavailable`，不發送已知會失敗的 web_search fallback 請求；其餘來源不受影響**。

申請步驟：登入 [market.cloud.edu.tw](https://market.cloud.edu.tw) → 會員中心 → 資料設定 → API應用服務 → 取得個人 API KEY，再以環境變數 `EDUMARKET_API_KEY` 傳入 server。

**Claude Desktop**：在對應 `mcpServers` 項加入 `env`：

```json
{
  "mcpServers": {
    "opendata-campus": {
      "command": "/絕對路徑/opendataCampus-MCP/.venv/bin/opendata-campus-mcp",
      "env": { "EDUMARKET_API_KEY": "<key>" }
    }
  }
}
```

**Claude Code**：以 `-e` 傳入環境變數：

```bash
claude mcp add opendata-campus -e EDUMARKET_API_KEY=<key> -- /絕對路徑/opendataCampus-MCP/.venv/bin/opendata-campus-mcp
```

---

## 測試

```bash
# 單元測試（82 個；service / browser_policy / source_router / edumarket / opendata / web_search / ceec_exam）— CI 在此 gate
pytest tests/ -v

# 端對端整合測試（教育大市集官方 API，需 EDUMARKET_API_KEY；未設時自動跳過）
EDUMARKET_API_KEY=<key> python scripts/integration_e2e.py

# 全來源 live smoke test（需網路，對 10 個內建來源各跑一次 browse 並回報健康度）
python scripts/smoke_sources.py
```

`scripts/smoke_sources.py` 是維護者用的 live 診斷工具（**非** CI gate）：對每個內建來源跑一次 `browse`，依連線結果標記 ✅ OK / ⚠️ EMPTY / 🔒 LOGIN / ❌ UNAVAILABLE，快速看出哪些來源的搜尋 / 解析器仍正常。最近實測見 [來源 live 健康度](sources.md#來源-live-健康度)。

`scripts/integration_e2e.py` 以教育大市集官方 API 走完整三段式流程：`discover`（找到教育大市集）→ `browse`（官方 v2 API 回傳含 `education_stage` / `subject` 的結構化結果）→ `read`（HTML best-effort 讀取單頁摘要）。需設 `EDUMARKET_API_KEY` 才會實際發送請求，未設時跳過。
