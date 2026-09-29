"""Redirect-aware HTTP requests with URL, body-size and content-type enforcement.

安全邊界（對應 security_best_practices_report.md SEC-3 / SEC-4）:
  1. 每一個 redirect hop 在「送出請求前」都先過 url_policy —— 防 SSRF(CWE-918)。
     httpx 的 follow_redirects=True 會直接跟隨 Location,上游站台被入侵或存在
     open redirect 時即可把請求導向 localhost / 169.254.169.254 等內部位址。
  2. 回應在「讀取完成前」即受 max_bytes 上限約束 —— 防資源耗盡(CWE-400/CWE-770)。
     先看 Content-Length 提早拒絕,再於串流累積時逐塊檢查(標頭可造假)。
  3. 最終回應的 Content-Type 需落在文字類白名單 —— 避免把二進位內容餵進 HTML parser。
     僅檢查最終回應:3xx 的 body 不會被解析,其 Content-Type 無意義。

browser_policy 為選用:自帶速率控制的 adapter(如 CeecExamAdapter 的受控分頁)
傳 None,避免同一次請求被計兩次而誤觸自身的分頁上限。
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# 5 MiB:官方教育平台的搜尋頁/JSON 回應遠低於此;超過即視為異常或攻擊。
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# 本專案只解析 HTML 與 JSON;其餘型別一律拒收而非硬餵進 parser。
_ALLOWED_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/ld+json",
)

# 重建 Response 時必須丟棄的標頭:aiter_bytes() 已解壓並改變長度,
# 沿用舊值會讓 .text / .json() 依據錯誤的編碼或長度解讀 body。
_STALE_BODY_HEADERS = ("content-encoding", "content-length", "transfer-encoding")

# 無限 redirect 迴圈的硬上限(browser_policy 不一定存在時仍需保護)。
_MAX_REDIRECTS = 5


def _check_content_type(response: httpx.Response) -> None:
    raw = response.headers.get("Content-Type", "")
    media_type = raw.split(";", 1)[0].strip().lower()
    # 缺 Content-Type 視為可接受(部分政府站台不送);有值則必須落在白名單。
    if media_type and not media_type.startswith(_ALLOWED_CONTENT_TYPES):
        raise PolicyViolationError(
            f"outbound response content type is not allowed: {media_type}"
        )


async def _get_bounded(
    client: httpx.AsyncClient, url: str, *, max_bytes: int
) -> httpx.Response:
    """GET *url* 並在累積超過 max_bytes 前中止,回傳可正常取用 .text/.json() 的 Response。"""
    async with client.stream("GET", url, follow_redirects=False) as streamed:
        declared = streamed.headers.get("Content-Length")
        if declared is not None:
            try:
                if int(declared) > max_bytes:
                    raise PolicyViolationError(
                        f"outbound response exceeds {max_bytes} bytes "
                        f"(Content-Length={declared})"
                    )
            except ValueError:
                pass  # 標頭畸形 → 交給下面的逐塊檢查

        body = bytearray()
        async for chunk in streamed.aiter_bytes():
            body += chunk
            if len(body) > max_bytes:
                raise PolicyViolationError(
                    f"outbound response exceeds {max_bytes} bytes"
                )

        headers = [
            (k, v)
            for k, v in streamed.headers.multi_items()
            if k.lower() not in _STALE_BODY_HEADERS
        ]
        return httpx.Response(
            status_code=streamed.status_code,
            headers=headers,
            content=bytes(body),
            request=streamed.request,
        )


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    browser_policy: BrowserPolicy | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> httpx.Response:
    """GET an allowed URL, validating every redirect before it is requested."""
    current_url = url
    pages_used = 0

    while True:
        url_policy.validate(current_url)
        if browser_policy is not None:
            browser_policy.check_page_limit(pages_used)
            host = urlparse(current_url).hostname or ""
            browser_policy.check_rate_limit(host.lower())
        response = await _get_bounded(client, current_url, max_bytes=max_bytes)
        pages_used += 1

        location = response.headers.get("Location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            _check_content_type(response)
            return response
        if pages_used > _MAX_REDIRECTS:
            raise PolicyViolationError(
                f"outbound request exceeded {_MAX_REDIRECTS} redirects"
            )
        current_url = urljoin(current_url, location)
