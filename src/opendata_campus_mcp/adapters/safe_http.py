"""Redirect-aware HTTP requests with URL and request-budget enforcement."""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# 固定上游 adapter 沒有 BrowserPolicy 的頁數預算兜底,需自帶跳轉上限避免無限迴圈
_MAX_REDIRECTS = 5


async def _follow_validated(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    before_request: Callable[[str], None] | None = None,
    max_redirects: int | None = None,
) -> httpx.Response:
    """GET *url*, re-validating每一次 redirect 的目標後才發出下一個請求。

    httpx 的 follow_redirects=True 會直接跟進 Location,跳轉目標因此完全繞過
    url_policy — 這是 SSRF 的入口。此處一律以 follow_redirects=False 發送,
    自行逐跳驗證。
    """
    current_url = url
    redirects = 0

    while True:
        url_policy.validate(current_url)
        if before_request is not None:
            before_request(current_url)
        response = await client.get(current_url, follow_redirects=False)

        location = response.headers.get("Location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response

        redirects += 1
        if max_redirects is not None and redirects > max_redirects:
            raise PolicyViolationError("outbound URL exceeded redirect limit")
        current_url = urljoin(current_url, location)


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    browser_policy: BrowserPolicy,
) -> httpx.Response:
    """GET an allowed URL, validating every redirect before it is requested."""
    pages_used = 0

    def _before(current_url: str) -> None:
        nonlocal pages_used
        browser_policy.check_page_limit(pages_used)
        host = urlparse(current_url).hostname or ""
        browser_policy.check_rate_limit(host.lower())
        pages_used += 1

    return await _follow_validated(
        client, url, url_policy=url_policy, before_request=_before
    )


async def safe_get_fixed_host(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
) -> httpx.Response:
    """GET for adapters bound to one known upstream host.

    與 safe_get 同樣逐跳驗證,但不耗用 BrowserPolicy 的頁數/速率預算 —
    這些 adapter 已在自己的迴圈裡計費,重複計費會改變既有節流行為。
    """
    return await _follow_validated(
        client, url, url_policy=url_policy, max_redirects=_MAX_REDIRECTS
    )
