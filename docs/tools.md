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
    "name": "教育大市集",
    "reason": "教育部數位內容入口，提供各級教案、多媒體教材與學習活動",
    "official_url": "https://market.cloud.edu.tw",
    "education_stages": ["國小", "國中", "高中"],
    "categories": ["教案", "多媒體", "學習活動", "教材"],
    "directory_source": "TWCampus",
    "access_strategy": "OFFICIAL_API"
  }
]
```
</details>

## 2. `browse_education_source`

在指定官方教育平台上搜尋學習資源。

| 參數 | 型別 | 說明 |
|------|------|------|
| `source` | `str` | 平台名稱（如「教育大市集」）或官方 URL |
| `query` | `str` | 搜尋關鍵字 |
| `max_results` | `int` | 預設 5，上限 5 |

<details>
<summary>回傳範例</summary>

教育大市集為 `OFFICIAL_API` 來源，browse 走官方 v2 API，故 `education_stage`（來自 API 的 `edugrade`）與 `subject`（來自 `domain`）為**有值**結構化欄位：

```json
{
  "source": "教育大市集",
  "official_url": "https://market.cloud.edu.tw",
  "query": "理化",
  "total_returned": 5,
  "results": [
    {
      "title": "理化反應與能量",
      "url": "https://market.cloud.edu.tw/resources/1234567",
      "summary": "…",
      "source_name": "教育大市集",
      "source_url": "https://market.cloud.edu.tw",
      "education_stage": "國中",
      "subject": "自然科學、理化"
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

與 browse 不同，`read` 走 web_search 的 HTML 擷取（best-effort）：即使是 `OFFICIAL_API` 來源，單頁的 `education_stage` / `subject` 仍可能為 `null`（官方 API 無 by-id 詳情端點，read 委派給 HTML reader）。

```json
{
  "url": "https://market.cloud.edu.tw/resources/1234567",
  "title": "理化反應與能量 - 教育大市集",
  "summary": "… 介紹理化反應中的能量變化，適用國中自然領域教學 …",
  "publisher": "教育大市集",
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
