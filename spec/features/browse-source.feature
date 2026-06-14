# language: zh-TW
Feature: 官方教育平台搜尋
  作為 Claude/Agent
  我想要在指定官方教育平台上搜尋學習資源
  以便找到符合使用者需求的學習材料

  Scenario: 在已知平台以名稱搜尋
    Given source="教育大市集" 且官方網址已知
    When 我以「密度 八年級」查詢
    Then 應回傳最多 5 筆搜尋結果
    And 每筆結果包含 title、url、summary、source_name、source_url

  Scenario: 以 URL 直接指定平台
    Given source="https://market.cloud.edu.tw"
    When 呼叫 browse_education_source
    Then 應解析出對應的已知平台並執行搜尋

  Scenario: 回傳結果必須標註來源
    Given 任意來源平台
    When 搜尋完成
    Then 每筆結果的 source_name 與 source_url 不可為空字串

  Scenario: 搜尋結果超過限制時截斷
    Given 平台搜尋結果超過 5 筆
    When 呼叫 browse_education_source(max_results=5)
    Then 回傳筆數不應超過 5
    And 結果物件包含 total_returned 欄位

  Scenario: 平台不可存取時回傳結構化錯誤
    Given source URL 無法連線（連線逾時或 5xx）
    When 呼叫 browse_education_source
    Then 應回傳 {"error": "source_unavailable", "source": ..., "url": ...}
    And 不拋出未捕捉例外

  Scenario: 需要登入的頁面拒絕存取
    Given 平台回傳 401/403
    When 呼叫 browse_education_source
    Then 應回傳 {"error": "login_required", ...}
    And 不嘗試自動繞過登入
