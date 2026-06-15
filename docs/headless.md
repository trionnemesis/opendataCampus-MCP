# 無頭瀏覽策略與雲端服務評估

> ← 回到 [README](../README.md)

本文件記錄本專案對「無頭瀏覽（headless browsing）」的策略取捨，以及對外部雲端無頭瀏覽服務（以 **Browserbase Browse CLI / browse.sh** 為代表）的評估結論，作為架構決策記錄（ADR）。

---

## 現況：主力 httpx + BS4，Playwright 後備預設停用

| 層 | 元件 | 狀態 |
|----|------|------|
| 主力抓取 | [`adapters/web_search.py`](../src/opendata_campus_mcp/adapters/web_search.py)（`httpx` + BeautifulSoup） | 啟用 |
| 無頭後備 | [`adapters/headless.py`](../src/opendata_campus_mcp/adapters/headless.py)（Playwright） | **預設停用**，需明確 `enabled=True` |

`HeadlessAdapter` 的瀏覽範圍被刻意限制：單頁、只抽 `<main>` 內的連結、不遞迴、不存 HTML / 截圖。預設停用是合規設計——對應 [瀏覽政策護欄](compliance.md#瀏覽政策合規護欄)（每域 3 req/min、每次 2 頁、禁排程、禁遞迴）。

**何時才真的需要無頭瀏覽？** JS-heavy SPA、反爬蟲 / Cloudflare、登入牆、需互動填表。目前 10 個內建台灣官方教育平台多為 server-rendered HTML，`httpx + BS4` 已足夠，故後備預設關閉。

---

## 評估：Browserbase Browse CLI / browse.sh

**結論：不建議引入本專案。** 它與本專案處於**同一抽象層**（都是「給 agent 用的瀏覽工具」），而非可作為下游基礎設施的無頭瀏覽器。加上 Node-only、需求過輕、合規方向相反三點，投報率為負。

### 三層對位：它的層級被搞錯了

| 層級 | 角色 | 對應 |
|------|------|------|
| **Agent 工具層** | 提供 agent「瀏覽某領域」的能力 | **本 MCP server** ⟷ **Browse CLI / browse.sh**（競品，同層） |
| **瀏覽器執行層** | 實際開瀏覽器、渲染、互動 | 本地 Playwright ⟷ **Browserbase 雲端瀏覽器** |
| **知識 / playbook 層** | 固化「如何導航特定站」 | 本專案 `source_cache._CATALOG` ⟷ **browse.sh skills** |

`browse.sh` 自身定位的目標使用者是 **AI agent**，要解決「agent 每次重新發現網站的 discovery tax」。但 `opendata_campus_mcp` **本身就是**那個給 agent 用的工具層——已用 `source_router` + `source_cache` 自行實作了 browse.sh 想提供的東西。Browse CLI 不是補下游，而是與本專案搶同一個位置。

> `browse.sh` 的 skill（`SKILL.md` = selectors + endpoints + gotchas + fallback）與本專案 [`source_cache.py`](../src/opendata_campus_mcp/repository/source_cache.py) 的 `_CATALOG` 是**同構概念**。這佐證本專案設計方向與業界趨勢一致——但屬於「概念驗證」，不是「該引入」的理由。

### 三個硬傷

1. **語言錯配（Node vs Python）**　Browse CLI 是 `npm i -g browse`，**無 Python SDK**。要塞進 FastMCP server 只能 subprocess 呼叫 Node CLI——production 反模式（冷啟動、錯誤傳播、多一套 Node runtime）。它的設計場景是「AI coding agent 在 terminal 用」，非後端 runtime component。

2. **需求過輕**　本專案瀏覽需求極輕（單頁、抓連結、不遞迴、3 req/min、不存全文）。Browserbase / Browse CLI 的賣點（JS-heavy SPA、反爬、登入、stealth/proxy/captcha）目前一個都用不到。

3. **合規方向相反（最該警惕）**　本專案核心不變量是「克制」（服務條款禁止大量下載 → 刻意限速、不遞迴、不排程、後備預設關）。Browserbase 主打 stealth、proxy rotation、captcha solving、大規模 concurrent sessions——為了**突破網站防線、規模化抓取**，與本專案合規哲學反向。對**政府網站**用 stealth/proxy 是合規與信譽風險。
   - 附帶風險：走 Browserbase 雲端 = 對台灣政府站的請求 / 回應經過**美國第三方雲**，資料保留 7 天（Free/Dev）——對政府資料專案是新的資料出境 / 主權風險面。

### 唯一站得住腳的採用場景（未來，非現在）

若日後出現「**某個必須 JS render、且服務條款允許自動化存取**的台灣教育平台」，屆時該比較的不是 Browse CLI，而是用 **Browserbase 雲端瀏覽器 API** 當 `HeadlessAdapter` 的後端：

- Browserbase 有 **Python SDK**，支援 **Playwright connect over CDP**——[`headless.py`](../src/opendata_campus_mcp/adapters/headless.py) 的 `chromium.launch()` 幾乎只需換成 `chromium.connect_over_cdp(...)`，改動最小。
- 好處：免維護本地 Chromium、server / CI 無 GUI 也能跑、concurrent 受控。
- 注意：這是**雲端 Playwright**，與 Browse CLI（agent CLI 工具）是兩回事。

---

## 決策

1. **短期維持現狀**：`httpx + BS4` 主力 + Playwright 後備（停用）。不引入 Browse CLI / browse.sh。
2. **升級觸發條件（寫死，避免日後拍腦袋）**：當且僅當出現「目標站必須 JS render **且**條款允許自動化」→ 才評估雲端 headless，且優先 **Browserbase Python SDK 直連（CDP）**，而非 Browse CLI。
3. **browse.sh 的 skill 概念可當設計鏡子**：確認 `_CATALOG` + `source_router` 方向正確，但不需要外部依賴。

---

## 參考來源

- [Browse CLI — Browserbase Docs](https://docs.browserbase.com/integrations/skills/browse-cli)
- [Browse.sh announcement — Browserbase Blog](https://www.browserbase.com/blog/browse.sh)
- [Browserbase Pricing](https://www.browserbase.com/pricing)
- [The most powerful CLI for your agents — Browserbase](https://www.browserbase.com/browse-cli)
- [@browserbasehq/browse-cli — npm](https://www.npmjs.com/package/@browserbasehq/browse-cli)
