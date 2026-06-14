# language: zh-TW
Feature: 瀏覽器使用政策
  作為系統管理者
  我想要確保無頭瀏覽器的使用受到嚴格限制
  以避免違反 TWCampus 服務條款中的「大量下載」禁令

  Background:
    Given BrowserPolicy 設定為預設值（max_pages=2, max_req_per_min=3）

  Scenario: 每分鐘不超過 3 次同域請求
    Given 過去 60 秒已對 twcampus.org 發送 3 次請求
    When 嘗試發送第 4 次請求
    Then 應拋出 RateLimitError
    And 錯誤訊息包含請求次數限制說明

  Scenario: 不同網域的計數器獨立
    Given 對 twcampus.org 已發送 3 次請求（達上限）
    When 對 market.cloud.edu.tw 發送請求
    Then 不應拋出 RateLimitError（不同網域獨立計算）

  Scenario: 60 秒視窗過後計數器重置
    Given 60 秒前已對 twcampus.org 發送 3 次請求
    When 60 秒後再次發送請求
    Then 不應拋出 RateLimitError（舊計數已過期）

  Scenario: 每次請求最多 2 個頁面
    Given pages_used=2（已用滿）
    When 嘗試 check_page_limit(pages_used=2)
    Then 應拋出 PolicyViolationError

  Scenario: 未達頁面限制時可繼續
    Given pages_used=0 或 pages_used=1
    When 呼叫 check_page_limit
    Then 不應拋出任何例外

  Scenario: 排程呼叫不觸發任何 TWCampus 請求
    Given 系統啟動且無使用者互動
    When 無工具被呼叫
    Then 不應有任何對 twcampus.org 的 HTTP 請求

  Scenario: 回傳結果必須包含來源 URL
    Given 任意查詢工具呼叫
    When 工具回傳結果
    Then 所有結果項目必須含有 official_url 或 url 欄位
