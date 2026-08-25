"""Redirect-aware HTTP requests with URL and request-budget enforcement."""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# 單一回應 body 上限(CWE-400)。url_policy 只保證「主機在目錄內」,不保證
# 對方回多大;政府平台故障、被入侵或中間人都可能回一份無上限的 body,而
# 呼叫端(_parse_results / _extract_fields)是直接 BeautifulSoup(resp.text)。
# 教育平台搜尋結果頁實測 <1MB,16MB 留足餘裕又擋得住無限串流。
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class ResponseTooLargeError(RuntimeError):
    """回應 body 超過 MAX_RESPONSE_BYTES,已在讀完前中止。"""


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    browser_policy: BrowserPolicy,
) -> httpx.Response:
    """GET an allowed URL, validating every redirect before it is requested."""
    current_url = url
    pages_used = 0

    while True:
        url_policy.validate(current_url)
        browser_policy.check_page_limit(pages_used)
        host = urlparse(current_url).hostname or ""
        browser_policy.check_rate_limit(host.lower())
        async with client.stream(
            "GET", current_url, follow_redirects=False
        ) as response:
            pages_used += 1
            location = response.headers.get("Location")
            if response.status_code in _REDIRECT_STATUSES and location:
                current_url = urljoin(current_url, location)
                continue
            # 終端回應才把 body 讀進來,且逐 chunk 累計、超限即中止
            return _materialize(await _read_capped(response), response)


async def _read_capped(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ResponseTooLargeError(
                f"response exceeded {MAX_RESPONSE_BYTES} bytes, aborted:"
                f" {response.request.url}"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _materialize(body: bytes, streamed: httpx.Response) -> httpx.Response:
    """把已讀完的 stream 回應轉成一般 Response,讓呼叫端照舊用 .text/.json()。"""
    # 去掉描述傳輸方式的 header:body 已解碼且長度改由 content 決定
    headers = [
        (k, v)
        for k, v in streamed.headers.multi_items()
        if k.lower() not in ("content-length", "content-encoding", "transfer-encoding")
    ]
    return httpx.Response(
        streamed.status_code,
        headers=headers,
        content=body,
        request=streamed.request,
    )
