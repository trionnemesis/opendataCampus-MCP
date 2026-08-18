"""Redirect-aware HTTP requests with URL and request-budget enforcement."""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# 抓取內容前先設定 body 大小上限，避免非預期的巨大/串流回應造成記憶體或延遲風險
# （對應 security_best_practices_report.md SEC-4）；HTML 頁面遠低於此門檻，摘要另有 500 字元上限。
_MAX_RESPONSE_BYTES = 2_000_000

# 固定上游 adapter 沒有 BrowserPolicy 的頁數預算兜底,需自帶跳轉上限避免無限迴圈
_MAX_REDIRECTS = 5


async def _follow_validated(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    before_request: Callable[[str], None] | None = None,
    max_redirects: int | None = None,
    max_response_bytes: int | None = None,
) -> httpx.Response:
    """GET *url*, re-validating每一次 redirect 的目標後才發出下一個請求。

    httpx 的 follow_redirects=True 會直接跟進 Location,跳轉目標因此完全繞過
    url_policy — 這是 SSRF 的入口。此處一律以 follow_redirects=False 發送,
    自行逐跳驗證。

    max_response_bytes 為 None 時直接讀取整個 body（固定上游的資料下載可能
    遠大於 HTML 頁面，不套用網頁用的 2MB 上限）；給定時改以 stream 模式讀取
    並強制上限。
    """
    current_url = url
    redirects = 0

    while True:
        url_policy.validate(current_url)
        if before_request is not None:
            before_request(current_url)

        if max_response_bytes is None:
            response = await client.get(current_url, follow_redirects=False)
        else:
            request = client.build_request("GET", current_url)
            response = await client.send(request, stream=True)

        location = response.headers.get("Location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            if max_response_bytes is not None:
                await _read_within_budget(response, max_response_bytes)
            return response

        if max_response_bytes is not None:
            await response.aclose()
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
    max_response_bytes: int = _MAX_RESPONSE_BYTES,
) -> httpx.Response:
    """GET an allowed URL, validating every redirect before it is requested.

    回應 body 以 stream 模式讀取並強制 max_response_bytes 上限；超出上限時中止讀取
    並關閉連線，拋出 PolicyViolationError（不將已讀取的部分內容回傳給呼叫端）。
    """
    pages_used = 0

    def _before(current_url: str) -> None:
        nonlocal pages_used
        browser_policy.check_page_limit(pages_used)
        host = urlparse(current_url).hostname or ""
        browser_policy.check_rate_limit(host.lower())
        pages_used += 1

    return await _follow_validated(
        client,
        url,
        url_policy=url_policy,
        before_request=_before,
        max_response_bytes=max_response_bytes,
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


async def _read_within_budget(response: httpx.Response, max_bytes: int) -> None:
    """讀取 response body 至 response._content，超出 max_bytes 則中止並拋出例外。"""
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > max_bytes:
            await response.aclose()
            raise PolicyViolationError(
                f"response body exceeds max_response_bytes={max_bytes}"
            )

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            await response.aclose()
            raise PolicyViolationError(
                f"response body exceeds max_response_bytes={max_bytes}"
            )
        chunks.append(chunk)
    response._content = b"".join(chunks)  # noqa: SLF001 — 等同 httpx.Response.aread() 的內部行為
