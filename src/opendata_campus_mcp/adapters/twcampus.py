"""TwCampusDirectoryAdapter — TWCampus 目錄導航器。

行為規範（對應 spec/features/browser-policy.feature）：
  - 每次請求至多開啟 2 個頁面（BrowserPolicy.check_page_limit）
  - 受 BrowserPolicy 速率限制（3 req/min）
  - 僅讀取首頁平台列表，不遞迴跟進子連結
  - 不儲存完整 HTML；只保留平台名稱、URL 與描述
  - 使用 httpx（HTTP/SSR）；若頁面需 JS 渲染則回傳空列表（降級至本地快取）
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from opendata_campus_mcp.contracts import (
    AccessStrategy,
    DiscoveryRequest,
    EducationSource,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy

log = logging.getLogger(__name__)

_TWCAMPUS_URL = "https://twcampus.org/"
_TWCAMPUS_DOMAIN = "twcampus.org"
_USER_AGENT = "Education-Resource-Browser-MCP/1.0 (non-commercial; user-triggered)"
_MIN_TITLE_LEN = 2
_MAX_DESCRIPTION_CHARS = 200


class TwCampusDirectoryAdapter:
    source_id = "twcampus-directory"
    access_strategy = AccessStrategy.TWCAMPUS_DIRECTORY

    def __init__(self, policy: BrowserPolicy) -> None:
        self._policy = policy
        self._client = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=15.0,
            follow_redirects=True,
        )

    async def discover(self, request: DiscoveryRequest) -> list[EducationSource]:
        """從 TWCampus 首頁解析平台列表並依 request 過濾。

        BrowserPolicy 限制：最多 1 頁（首頁），受速率限制。
        """
        self._policy.check_rate_limit(_TWCAMPUS_DOMAIN)
        self._policy.check_page_limit(pages_used=0)  # 首頁 = page 1/2

        try:
            resp = await self._client.get(_TWCAMPUS_URL)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("TWCampus fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        all_sources = self._parse_platform_cards(soup)
        filtered = self._filter_relevant(all_sources, request)
        return filtered[: request.max_sources]

    def _parse_platform_cards(self, soup: BeautifulSoup) -> list[EducationSource]:
        sources: list[EducationSource] = []
        main = soup.find("main") or soup.find(id="main") or soup.find("body")
        if not main:
            return []

        for link in main.find_all("a", href=True):
            href: str = link["href"]
            title = link.get_text(strip=True)

            if len(title) < _MIN_TITLE_LEN:
                continue
            if not href.startswith("http"):
                continue
            if _TWCAMPUS_DOMAIN in href:
                continue  # 跳過 TWCampus 內部連結

            # 試圖抓相鄰描述文字
            description = ""
            parent = link.parent
            if parent:
                desc_el = parent.find(["p", "span", "small"])
                if desc_el and desc_el != link:
                    description = desc_el.get_text(strip=True)[:_MAX_DESCRIPTION_CHARS]

            sources.append(
                EducationSource(
                    name=title,
                    official_url=href,
                    description=description,
                    access_strategy=AccessStrategy.WEB_SEARCH,
                    directory_source="TWCampus",
                )
            )

        return sources

    def _filter_relevant(
        self,
        sources: list[EducationSource],
        request: DiscoveryRequest,
    ) -> list[EducationSource]:
        query_tokens = set(request.query.lower().split())

        def score(s: EducationSource) -> int:
            if request.education_stage and s.education_stages:
                if request.education_stage not in s.education_stages:
                    return -1
            text = f"{s.name} {s.description}".lower()
            return sum(1 for t in query_tokens if t in text)

        scored = [(score(s), s) for s in sources]
        scored.sort(key=lambda x: -x[0])
        return [s for sc, s in scored if sc >= 0]

    async def aclose(self) -> None:
        await self._client.aclose()
