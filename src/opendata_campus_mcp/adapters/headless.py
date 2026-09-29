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
from urllib.parse import quote, urlencode

from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    EducationSource,
    SearchResult,
)
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.repository.source_cache import get_known_sources

log = logging.getLogger(__name__)


class HeadlessAdapter:
    """Playwright 後備；明確 enabled=True 才可使用。"""

    access_strategy = AccessStrategy.HEADLESS_BROWSER
    source_id = "headless-browser"

    def __init__(self, enabled: bool = False) -> None:
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
        # goto() 的目標仍須落在 catalog 白名單內(headless 亦是對外請求)
        self._url_policy = PublicEducationUrlPolicy.from_sources(
            get_known_sources().values()
        )

    def build_search_url(self, source: EducationSource, query: str) -> str:
        """組出 goto() 目標並驗證。

        query 必須編碼:未編碼時 `&`/`#` 會被當成 URL 語法,呼叫端即可注入額外
        query 參數或截斷 URL(CWE-116/CWE-74)。組好的 URL 仍須過 catalog 白名單。
        """
        search_url = (
            f"{source.official_url.rstrip('/')}"
            f"?{urlencode({'q': query}, quote_via=quote)}"
        )
        self._url_policy.validate(search_url)
        return search_url

    async def browse(
        self, source: EducationSource, request: BrowseRequest
    ) -> list[SearchResult]:
        # Playwright import 延遲至實際呼叫，避免啟動成本
        from playwright.async_api import async_playwright  # type: ignore[import]

        search_url = self.build_search_url(source, request.query)
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

        return [
            SearchResult(
                title=item["title"],
                url=item["url"],
                summary="",
                source_name=source.name,
                source_url=source.official_url,
            )
            for item in raw[: request.max_results]
        ]
