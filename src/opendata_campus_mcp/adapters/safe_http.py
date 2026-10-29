"""Redirect-aware HTTP requests with URL, budget, size and content-type limits."""
from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# 回應讀取上限。browse/read 只解析教育資源 HTML 頁(實測數十 KB ~ 數百 KB),
# 5MB 遠高於任何正常頁面。無上限時 httpx 會把整份 body 讀進記憶體再交給
# BeautifulSoup 解析 —— 被指向大型檔案時單次工具呼叫即可耗盡記憶體
# (CWE-400);摘要截斷發生在解析「之後」,救不了下載與解析階段。
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# safe_get 服務的是 HTML 解析路徑(BeautifulSoup)。明確宣告非 HTML/文字型別
# 不予下載,避免把二進位大檔(影音、壓縮檔、PDF)拉進解析器。
# 刻意「只在 Content-Type 存在且不在白名單時」拒絕:部分政府教育站台不回
# Content-Type,一律嚴拒會打斷既有可用來源;缺標頭的大檔仍由上面的大小上限兜底。
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "text/xml",
        "application/xml",
    }
)


ALLOWED_CONTENT_TYPES = (*sorted(_ALLOWED_CONTENT_TYPES), "application/json")


class ResponseTooLargeError(PolicyViolationError):
    """Response exceeds its byte budget or permitted media types."""


def _check_content_type(
    response: httpx.Response, url: str,
    allowed: Iterable[str] | None = _ALLOWED_CONTENT_TYPES,
) -> None:
    # 呼叫端先依 4xx/5xx 狀態分類錯誤,不解析其 body;大小上限仍由 _read_capped 執行。
    if response.is_error or allowed is None:
        return
    raw = response.headers.get("Content-Type", "")
    media_type = raw.split(";", 1)[0].strip().lower()
    if media_type and media_type not in allowed:
        raise ResponseTooLargeError(
            f"outbound response content type is not allowed: {media_type}"
        )


async def _read_capped(response: httpx.Response, url: str, max_bytes: int) -> bytes:
    """串流讀取 body,累計超過上限即中止 — 不把超量內容讀完才檢查。

    Content-Length 若已宣告超量則直接拒絕,連下載都不開始。
    """
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLargeError(
            f"outbound response exceeds {max_bytes} bytes (declared)"
        )

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(
                f"outbound response exceeds {max_bytes} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    browser_policy: BrowserPolicy,
    max_bytes: int | None = None,
) -> httpx.Response:
    """GET an allowed URL, validating every redirect before it is requested.

    回應以串流讀取並受 MAX_RESPONSE_BYTES 與 Content-Type 白名單約束;
    回傳的 Response 仍為已載入 body 的一般 httpx.Response(`.text` / `.json()`
    行為不變),呼叫端無需改動。
    """
    max_bytes = MAX_RESPONSE_BYTES if max_bytes is None else max_bytes
    current_url = url
    pages_used = 0

    while True:
        url_policy.validate(current_url)
        browser_policy.check_page_limit(pages_used)
        host = urlparse(current_url).hostname or ""
        browser_policy.check_rate_limit(host.lower())

        request = client.build_request("GET", current_url)
        response = await client.send(request, follow_redirects=False, stream=True)
        pages_used += 1

        location = response.headers.get("Location")
        if response.status_code in _REDIRECT_STATUSES and location:
            await response.aclose()
            current_url = urljoin(current_url, location)
            continue

        try:
            _check_content_type(response, current_url)
            body = await _read_capped(response, current_url, max_bytes)
        finally:
            await response.aclose()

        # aiter_bytes 回傳的是「已解碼」的位元組,故重建時移除 transfer 相關
        # 標頭,避免 httpx 對同一份 body 二次解碼或回報錯誤長度。
        headers = [
            (k, v)
            for k, v in response.headers.multi_items()
            if k.lower() not in ("content-encoding", "content-length")
        ]
        return httpx.Response(
            status_code=response.status_code,
            headers=headers,
            content=body,
            request=request,
        )



async def bounded_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int | None = None,
    allowed_content_types: Iterable[str] | None = ALLOWED_CONTENT_TYPES,
    follow_redirects: bool | None = None,
) -> httpx.Response:
    """Read a fixed-endpoint response with the same decoded-byte budget."""
    max_bytes = MAX_RESPONSE_BYTES if max_bytes is None else max_bytes
    request = client.build_request("GET", url)
    redirects = client.follow_redirects if follow_redirects is None else follow_redirects
    # httpx auto-follow eagerly buffers intermediate bodies, bypassing our cap.
    # Follow its prepared next_request while closing redirect bodies unread.
    redirects_used = 0
    while True:
        response = await client.send(request, stream=True, follow_redirects=False)
        if not redirects or response.next_request is None:
            break
        next_request = response.next_request
        await response.aclose()
        redirects_used += 1
        if redirects_used > client.max_redirects:
            raise httpx.TooManyRedirects("Exceeded maximum allowed redirects.", request=request)
        request = next_request
    try:
        _check_content_type(response, url, allowed_content_types)
        body = await _read_capped(response, url, max_bytes)
    finally:
        await response.aclose()
    headers = [
        (k, v) for k, v in response.headers.multi_items()
        if k.lower() not in ("content-encoding", "content-length")
    ]
    return httpx.Response(
        status_code=response.status_code,
        headers=headers,
        content=body,
        request=response.request,
        extensions=response.extensions,
    )
