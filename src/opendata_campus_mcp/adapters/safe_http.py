"""Redirect-aware HTTP requests with URL and request-budget enforcement."""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# 抓取內容前先設定 body 大小上限，避免非預期的巨大/串流回應造成記憶體或延遲風險
# （對應 security_best_practices_report.md SEC-4）；HTML 頁面遠低於此門檻，摘要另有 500 字元上限。
_MAX_RESPONSE_BYTES = 2_000_000


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
    current_url = url
    pages_used = 0

    while True:
        url_policy.validate(current_url)
        browser_policy.check_page_limit(pages_used)
        host = urlparse(current_url).hostname or ""
        browser_policy.check_rate_limit(host.lower())

        request = client.build_request("GET", current_url)
        response = await client.send(request, stream=True)
        pages_used += 1

        location = response.headers.get("Location")
        if response.status_code in _REDIRECT_STATUSES and location:
            await response.aclose()
            current_url = urljoin(current_url, location)
            continue

        await _read_within_budget(response, max_response_bytes)
        return response


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
