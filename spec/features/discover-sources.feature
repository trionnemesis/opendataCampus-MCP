# language: zh-TW
Feature: 教育資源來源探索
  作為 Claude/Agent
  我想要從 TWCampus 目錄找到相關的官方教育平台
  以便將使用者的問題路由至正確的學習資源

  Scenario: 依關鍵字找到教育平台
    Given TWCampus 首頁可存取
    When 我以「國中自然探究教案」查詢
    Then 應回傳最多 3 個相關教育平台
    And 每個平台包含 name、official_url、categories 與 directory_source

  Scenario: 教育階段過濾排除不符合的平台
    Given 平台列表含「教育大市集」（適用 國小/國中/高中）與「因材網」（適用 國小/國中）
    When 我指定 education_stage="高中" 查詢
    Then 「因材網」不應出現在回傳結果中
    And directory_source 標記為 "TWCampus"

  Scenario: 無相關平台時回傳空集合
    Given 已知平台目錄與 TWCampus 均無匹配項目
    When 查詢字串無法匹配任何平台
    Then 應回傳空陣列，不拋出例外

  Scenario: 優先使用本地目錄，不足時補充 TWCampus
    Given 本地目錄有 1 個匹配平台，查詢 max_sources=3
    When 呼叫 discover_education_sources
    Then 系統應補充呼叫 TWCampus 以取得更多結果
    And TWCampus 呼叫次數不超過 BrowserPolicy 限制

  Scenario: 每次請求最多開啟 2 個 TWCampus 頁面
    Given 瀏覽政策設定 max_pages_per_request=2
    When TWCampus adapter 嘗試開啟第 3 個頁面
    Then 應拋出 PolicyViolationError
    And 不應繼續抓取後續頁面
