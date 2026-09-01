"""HeadlessAdapter — Playwright 後備（預設停用）。

此 adapter 僅在以下條件同時成立時才可實例化：
  1. 呼叫端明確傳入 enabled=True
  2. 系統管理員已評估瀏覽器政策合規性

設計原則（對應 spec/features/source-routing.feature）：
  - 不開啟超過 max_pages_per_request 個頁面
  - 不遞迴跟進連結
  - 不儲存完整 HTML 或截圖
  - 結果必須包含 source_url
"""
from __future__ import annotations

import logging
import warnings
from urllib.parse import quote

from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    EducationSource,
    SearchResult,
)
from opendata_campus_mcp.domain.url_policy import (
    PublicEducationUrlPolicy,
    safe_result_url,
)
from opendata_campus_mcp.repository.source_cache import get_known_sources

log = logging.getLogger(__name__)


class HeadlessAdapter:
    """Playwright 後備；明確 enabled=True 才可使用。"""

    access_strategy = AccessStrategy.HEADLESS_BROWSER
    source_id = "headless-browser"

    def __init__(
        self,
        enabled: bool = False,
        url_policy: PublicEducationUrlPolicy | None = None,
    ) -> None:
        if not enabled:
            raise RuntimeError(
                "HeadlessAdapter is disabled by default. "
                "Explicitly pass enabled=True after verifying browser policy compliance."
            )
        warnings.warn(
            "strategy_fallback=HEADLESS_BROWSER activated. "
            "Ensure BrowserPolicy compliance before production use.",
            stacklevel=2,
        )
        self._enabled = enabled
        self._url_policy = url_policy or PublicEducationUrlPolicy.from_sources(
            get_known_sources().values()
        )

    def _build_search_url(self, source: EducationSource, query: str) -> str:
        """組出搜尋 URL 並套用兩個護欄(與 WebSearchAdapter 的 safe_get 對齊)。

        1. query 必須 URL-encode。未編碼時 query 內的 & / # 會被當成語法
           字元,足以竄改甚至截斷整個 URL(CWE-20)。
        2. 送進瀏覽器前套用 url_policy。此 adapter 先前完全繞過目錄白名單
           —— 一個被污染的 source.official_url 就能讓無頭瀏覽器連往任意
           主機(CWE-918);驗證必須發生在 playwright 啟動之前。
        """
        search_url = f"{source.official_url.rstrip('/')}?q={quote(query, safe='')}"
        self._url_policy.validate(search_url)
        return search_url

    async def browse(
        self, source: EducationSource, request: BrowseRequest
    ) -> list[SearchResult]:
        # Playwright import 延遲至實際呼叫，避免啟動成本
        from playwright.async_api import async_playwright  # type: ignore[import]

        search_url = self._build_search_url(source, request.query)
        log.warning("headless browse: GET %s", search_url)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(search_url, wait_until="domcontentloaded")

            # 僅讀取當前頁面，禁止遞迴導航
            raw: list[dict[str, str]] = await page.locator("main").evaluate(
                """(main) => {
                    return Array.from(main.querySelectorAll('a'))
                        .filter(a => a.textContent && a.href && !a.href.startsWith('javascript'))
                        .map(a => ({ title: a.textContent.trim(), url: a.href }))
                        .filter(item => item.title.length >= 2)
                        .slice(0, 10);
                }"""
            )

            await page.close()
            await browser.close()

        # 頁內 JS 只濾掉 javascript:,data: / blob: 等仍會通過;統一走與其他
        # adapter 相同的 scheme 白名單,不把可執行連結交給 client(CWE-79)。
        results: list[SearchResult] = []
        for item in raw:
            url = safe_result_url(item["url"], search_url)
            if not url:
                continue
            results.append(
                SearchResult(
                    title=item["title"],
                    url=url,
                    summary="",
                    source_name=source.name,
                    source_url=source.official_url,
                )
            )
            if len(results) >= request.max_results:
                break
        return results
