# language: zh-TW
Feature: 資源存取策略路由
  作為系統核心路由器
  我想要依優先順序選擇最適合的存取策略
  以降低 HEADLESS_BROWSER 使用頻率並遵守 TWCampus 條款

  Scenario: 路由優先順序 OFFICIAL_API > OPEN_DATA > WEB_SEARCH > TWCAMPUS_DIRECTORY > HEADLESS_BROWSER
    Given 多個存取策略均可用
    When SourceRouter 選擇策略
    Then 選擇 priority 最低數字的策略（OFFICIAL_API=0 最優先）

  Scenario: OFFICIAL_API 可用時不啟動瀏覽器
    Given 目標平台 access_strategy=OFFICIAL_API
    When 查詢資源
    Then 使用 OFFICIAL_API 策略，不啟動 Playwright 或 HTTP 爬取

  Scenario: TWCampus 目錄僅作平台路由入口
    Given 需要發現新的教育平台
    When 呼叫 discover_education_sources
    Then TWCampus 僅回傳平台名稱、官方 URL 與分類
    And 不從 TWCampus 儲存或索引任何資源內容

  Scenario: HEADLESS_BROWSER 為最後手段且預設停用
    Given HeadlessAdapter 預設 enabled=False
    When 嘗試實例化 HeadlessAdapter(enabled=False)
    Then 應拋出 RuntimeError（禁止未授權使用）

  Scenario: 本地目錄命中時不觸發 TWCampus 請求
    Given 查詢能從本地 source_cache 找到 max_sources 個正分平台
    When 呼叫 discover_education_sources
    Then 不應對 twcampus.org 發送任何 HTTP 請求

  Scenario: 本地目錄不足時才補充 TWCampus
    Given 本地目錄正分匹配 < max_sources
    When 呼叫 discover_education_sources
    Then 系統補充呼叫 TWCampus，並合併去重後回傳
    And TWCampus 請求仍受 BrowserPolicy 速率限制
