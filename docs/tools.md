# MCP 工具 API

> ← 回到 [README](../README.md)

三段式導航：`discover`（找平台）→ `browse`（搜資源）→ `read`（讀摘要）。

## 1. `discover_education_sources`

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

## 2. `browse_education_source`

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

## 3. `read_education_resource`

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

---

## 錯誤回傳

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

> 速率與頁面上限的定義見 [合規與限制 — 瀏覽政策](compliance.md#瀏覽政策合規護欄)。
