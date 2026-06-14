# language: zh-TW
Feature: 單一教育資源讀取
  作為 Claude/Agent
  我想要讀取指定公開教育資源頁面的關鍵資訊
  以便提供使用者精確的資源摘要

  Scenario: 讀取公開資源頁面的指定欄位
    Given URL 為合法的公開教育資源頁面
    When 呼叫 read_education_resource(url, extract=["title", "summary"])
    Then 應回傳 title 與 summary 欄位
    And 回傳物件包含 url 欄位且等於輸入的 URL

  Scenario: 優先回傳 meta description 作為摘要
    Given 頁面含有 <meta name="description" content="...">
    When extract 包含 "summary"
    Then summary 應取自 meta description（不超過 500 字元）
    And 不應儲存完整 HTML 或截圖

  Scenario: 回傳物件 url 欄位必須與輸入一致
    Given 任何合法資源 URL
    When 讀取完成
    Then 回傳物件的 url 欄位必須等於輸入的 URL（不被重新導向 URL 覆蓋）

  Scenario: 非公開頁面（需登入）應拒絕
    Given URL 回傳 401/403
    When 呼叫 read_education_resource
    Then 應回傳 {"error": "login_required", "url": ...}
    And 不嘗試自動登入或繞過存取控制

  Scenario: 僅擷取指定欄位，不儲存全文
    Given 資源頁面有完整內文（>10000 字元）
    When extract 未指定 "full_text"
    Then 回傳內容 summary 不超過 500 字元
    And 不建立本地 HTML 快取
