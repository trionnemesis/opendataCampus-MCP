# 教育平台來源

> ← 回到 [README](../README.md)

## 內建教育平台目錄

定義於 [`repository/source_cache.py`](../src/opendata_campus_mcp/repository/source_cache.py)。

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
- **❌ DNS 失效**：[`source_cache.py`](../src/opendata_campus_mcp/repository/source_cache.py) 中這兩筆 `official_url` 已無法解析，需更新為現行網址。
- 此表為單一環境快照，僅供參考；請以你自己環境執行 `smoke_sources.py` 的結果為準。
