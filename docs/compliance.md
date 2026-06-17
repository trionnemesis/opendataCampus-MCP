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

- **各來源 live 可用性不一**：無 key smoke 實測 9 個內建來源中 6 個可正常 browse（因材網、教育部數位教學資源入口網、GEPT、國立公共資訊圖書館、學力認證、均一），其餘 3 個 FAIL（教育大市集無 key 降級後搜尋頁 404、CIRN 憑證名稱不符、國教院連線中斷）— 詳見 [來源 live 健康度](sources.md#來源-live-健康度)。可用性會隨各站改版與執行環境而變動。
- **`read` 的 `education_stage` / `subject` 為 best-effort**：教育大市集經官方 API 在 **browse** 已回傳結構化學制 / 領域；但 **read**（及其他 web_search 來源）仍走 [`web_search.py`](../src/opendata_campus_mcp/adapters/web_search.py) 的 HTML 擷取，這兩個欄位對多數來源仍可能為 `null`。
- **`discover` 的 TWCampus 降級是靜默的**：TWCampus 任何故障（含潛在程式錯誤）都會被吞為 `log.info` 後退回本地目錄，正常路徑與降級路徑對使用者輸出不易區分。
- **臺大開放式課程 NTU OCW 已移除**：該站全站 Cloudflare JS 挑戰加上 robots 明示封鎖 AI bot；基於本專案「不繞過存取控制」原則主動移除（非技術不可行），內建來源由 10 降為 9。
- **國中會考（cap.rcpet.edu.tw）排除**：該站 `robots.txt` 為 `Disallow: /`，與 NTU OCW 同屬「不繞過存取控制」標準，故 `search_exam_questions` 不納入會考；`exam_type` 傳「會考」等非白名單值會回 `unsupported_exam_type`。統測列為後續。
- **`search_exam_questions` 僅回 PDF 連結、不下載全文**：只解析 CEEC listing 表格並回傳官方下載連結字串，完全不 fetch / 不儲存 PDF 或 `.docx` 全文；受瀏覽政策單次 **2 頁** 上限約束，故單次僅涵蓋最新約 20 筆，`year` / `subject` 為 best-effort 解析。
- **無頭瀏覽器後備預設停用**：需 JavaScript 渲染的平台在未啟用 Playwright 時可能取不到內容。背後的策略取捨與雲端服務評估見 [無頭瀏覽策略](headless.md)。

---

## 合規聲明

本工具僅存取**公開**教育資源，遵守來源網站服務條款：不執行大量 / 排程下載、不遞迴爬取、不儲存完整內容、不嘗試登入或繞過任何存取控制。TWCampus 僅作為路由目錄使用。所有抓取均由使用者即時查詢觸發。`search_exam_questions` 僅回傳 CEEC 考古題的官方下載連結，不下載或儲存試題全文，並排除 `robots.txt` 明示封鎖的國中會考。教育大市集的官方 API 為平台核可之介接方式，API key 由使用者自行申請並注入（見 [安裝與設定](setup.md#教育大市集官方-api-key選用)）。
