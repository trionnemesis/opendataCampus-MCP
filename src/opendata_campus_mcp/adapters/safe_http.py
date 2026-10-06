"""Redirect-aware HTTP requests with URL, size and request-budget enforcement."""
from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# 單一回應 body 上限(CWE-400 / CWE-770)。
#
# 本專案抓的都是 HTML 搜尋頁、資源頁與 JSON 信封,正常都在數百 KB 以內。
# 無上限時 resp.text / resp.json() 會把整份 body 讀進記憶體:
# read_education_resource 接受任何位於 allowlist host 下的 URL,
# 其中包含該站台上的大型 PDF / ZIP / 影片 —— 呼叫端(LLM)只要指向其中一個
# 就能讓 server 配置數百 MB 記憶體,且不需要任何權限。
#
# 以 stream + aiter_bytes 逐塊累計,超限立即中止連線,不先把整份內容收下來。
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

# 只接受可解析成文字的回應。adapter 下游一律做 HTML/JSON 解析,
# 二進位檔(PDF/ZIP/影片)無論大小都不是有效輸入,在讀 body 前就拒絕,
# 比先下載 16 MiB 再發現解析不了便宜得多。Content-Type 缺漏時不阻擋
# (部分政府站台不送此 header),此時仍有大小上限兜底。
ALLOWED_CONTENT_TYPES: tuple[str, ...] = (
    "text/html",
    "text/plain",
    "text/xml",
    "application/xhtml+xml",
    "application/xml",
    "application/json",
)


class ResponseTooLargeError(PolicyViolationError):
    """回應 body 超出 MAX_RESPONSE_BYTES,或型別不是可解析的文字。

    繼承 PolicyViolationError —— MCP 工具層已針對該型別回結構化錯誤,
    不需要新增例外處理分支。
    """


def _check_content_type(
    response: httpx.Response, url: str, allowed: Iterable[str] | None
) -> None:
    if allowed is None:
        return  # 固定端點的 JSON API:上游實際 header 未經本機驗證,不設型別白名單
    # 只檢查 2xx:錯誤頁與轉址的 body 不會被下游解析
    if not (200 <= response.status_code < 300):
        return
    raw = response.headers.get("Content-Type")
    if not raw:
        return  # header 缺漏不阻擋,交給大小上限兜底
    media_type = raw.split(";", 1)[0].strip().lower()
    if media_type and media_type not in tuple(allowed):
        raise ResponseTooLargeError(
            f"outbound response content-type is not readable text: {media_type}"
        )


async def bounded_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int = MAX_RESPONSE_BYTES,
    allowed_content_types: Iterable[str] | None = ALLOWED_CONTENT_TYPES,
    follow_redirects: bool | None = None,
) -> httpx.Response:
    """GET *url*, refusing bodies above *max_bytes* before they are buffered.

    Returns a fully-read ``httpx.Response`` so callers keep using ``.text`` /
    ``.json()`` / ``.status_code`` unchanged. ``follow_redirects=None`` keeps
    whatever the client was configured with; ``allowed_content_types=None``
    disables the media-type allowlist and relies on *max_bytes* alone.
    """
    request = client.build_request("GET", url)
    redirects = (
        client.follow_redirects if follow_redirects is None else follow_redirects
    )
    response = await client.send(request, stream=True, follow_redirects=redirects)
    try:
        _check_content_type(response, url, allowed_content_types)
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLargeError(
                    f"outbound response body exceeds {max_bytes} bytes"
                )
            chunks.append(chunk)
        body = b"".join(chunks)
    finally:
        await response.aclose()

    return httpx.Response(
        status_code=response.status_code,
        headers=response.headers,
        content=body,
        request=response.request,
        extensions=response.extensions,
    )


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    browser_policy: BrowserPolicy,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> httpx.Response:
    """GET an allowed URL, validating every redirect before it is requested."""
    current_url = url
    pages_used = 0

    while True:
        url_policy.validate(current_url)
        browser_policy.check_page_limit(pages_used)
        host = urlparse(current_url).hostname or ""
        browser_policy.check_rate_limit(host.lower())
        response = await bounded_get(
            client, current_url, max_bytes=max_bytes, follow_redirects=False
        )
        pages_used += 1

        location = response.headers.get("Location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response
        current_url = urljoin(current_url, location)
