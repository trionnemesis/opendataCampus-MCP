"""safe_get response body size cap（SEC-4：抓取前限制 body 大小，避免記憶體/延遲風險）。

驗證：
  - Content-Length 宣告超出上限 → 中止讀取（不建立 body），拋出 PolicyViolationError。
  - 無 Content-Length 但實際串流超出上限（chunked）→ 中途中止，拋出 PolicyViolationError。
  - 上限內的正常回應仍可正確讀出 body（不影響既有行為）。
"""
from __future__ import annotations

import httpx
import pytest

from opendata_campus_mcp.adapters.safe_http import safe_get
from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_POLICY = PublicEducationUrlPolicy(["market.cloud.edu.tw"])
_URL = "https://market.cloud.edu.tw/resource/1"


@pytest.mark.asyncio
async def test_oversized_content_length_header_is_rejected_before_body_read():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Length": "100"},
            text="x" * 100,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(PolicyViolationError):
            await safe_get(
                client,
                _URL,
                url_policy=_POLICY,
                browser_policy=BrowserPolicy(),
                max_response_bytes=10,
            )
        assert calls == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_oversized_streamed_body_without_content_length_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="y" * 1000)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(PolicyViolationError):
            await safe_get(
                client,
                _URL,
                url_policy=_POLICY,
                browser_policy=BrowserPolicy(),
                max_response_bytes=50,
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_body_within_budget_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><title>ok</title></html>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        resp = await safe_get(
            client,
            _URL,
            url_policy=_POLICY,
            browser_policy=BrowserPolicy(),
            max_response_bytes=10_000,
        )
        assert "ok" in resp.text
    finally:
        await client.aclose()
