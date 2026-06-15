# 合規與限制

> ← 回到 [README](../README.md)

## 瀏覽政策（合規護欄）

護欄寫死於 [`domain/browser_policy.py`](../src/opendata_campus_mcp/domain/browser_policy.py)，無法由請求參數放寬。

| 政策 | 值 |
|------|----|
| 每次請求最多頁數 | **2 頁** |
| 同域每分鐘請求上限 | **3 次**（滑動視窗，per-domain） |
| 排程爬取 | **停用** |
| 遞迴導航 | **停用** |
| 完整 HTML 儲存 | **停用** |
| 向量索引 | **停用** |
| 無頭瀏覽器（Playwright） | 預設 **停用**，需明確 `enabled=True`（見 [無頭瀏覽策略](headless.md)） |
| 登入 / 繞過存取控制 | **永不嘗試** |

---

## 限制與已知問題

誠實標註目前邊界，供使用前評估：

- **各來源 live 可用性不一**：實測 10 個內建來源中 3 個可正常 browse（GEPT、均一、NTU OCW），3 個憑證相容性、2 個連線受阻、2 個 DNS 失效 — 詳見 [來源 live 健康度](sources.md#來源-live-健康度)。可用性會隨各站改版與執行環境而變動。
- **`read` 的 `education_stage` / `subject` 目前固定回傳 `null`**：[`web_search.py`](../src/opendata_campus_mcp/adapters/web_search.py) 尚未實作這兩個欄位的擷取邏輯。
- **`discover` 的 TWCampus 降級是靜默的**：TWCampus 任何故障（含潛在程式錯誤）都會被吞為 `log.info` 後退回本地目錄，正常路徑與降級路徑對使用者輸出不易區分。
- **NTU OCW 的 `browse` 為首頁列表而非關鍵字搜尋**：因目標站 WAF 限制，`query` 實際未對課程做過濾，回傳的是首頁近期課程清單，語意與「搜尋」略有落差。
- **無頭瀏覽器後備預設停用**：需 JavaScript 渲染的平台在未啟用 Playwright 時可能取不到內容。背後的策略取捨與雲端服務評估見 [無頭瀏覽策略](headless.md)。

---

## 合規聲明

本工具僅存取**公開**教育資源，遵守來源網站服務條款：不執行大量 / 排程下載、不遞迴爬取、不儲存完整內容、不嘗試登入或繞過任何存取控制。TWCampus 僅作為路由目錄使用。所有抓取均由使用者即時查詢觸發。
