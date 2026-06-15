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

執行階段相依套件：`fastmcp>=0.2.0`、`httpx>=0.27`、`beautifulsoup4>=4.12`。

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

設定完成後，於 client 中可看到 `discover_education_sources`、`browse_education_source`、`read_education_resource` 三個工具。完整 API 見 [MCP 工具](tools.md)。

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

`scripts/smoke_sources.py` 是維護者用的 live 診斷工具（**非** CI gate）：對每個內建來源跑一次 `browse`，依連線結果標記 ✅ OK / ⚠️ EMPTY / 🔒 LOGIN / ❌ UNAVAILABLE，快速看出哪些來源的搜尋 / 解析器仍正常。最近實測見 [來源 live 健康度](sources.md#來源-live-健康度)。

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
