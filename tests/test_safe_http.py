"""safe_get 的回應大小護欄(CWE-400)— 離線,httpx.MockTransport。

url_policy 保證「主機在目錄內」,不保證對方回多大;呼叫端會直接把
resp.text 丟進 BeautifulSoup,故 body 需在讀完前就有上限。
"""
from __future__ import annotations

import httpx
import pytest

from opendata_campus_mcp.adapters import safe_http
from opendata_campus_mcp.adapters.safe_http import ResponseTooLargeError, safe_get
from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_ALLOWED = "https://market.cloud.edu.tw/page"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _get(client: httpx.AsyncClient, url: str = _ALLOWED) -> httpx.Response:
    return await safe_get(
        client,
        url,
        url_policy=PublicEducationUrlPolicy(["market.cloud.edu.tw"]),
        browser_policy=BrowserPolicy(),
    )


@pytest.mark.asyncio
async def test_normal_body_is_returned_intact():
    html = "<html><title>ok</title></html>"
    async with _client(lambda _r: httpx.Response(200, text=html)) as client:
        resp = await _get(client)
    assert resp.status_code == 200
    assert resp.text == html


@pytest.mark.asyncio
async def test_oversized_body_aborted_before_full_read(monkeypatch):
    monkeypatch.setattr(safe_http, "MAX_RESPONSE_BYTES", 1024)
    sent = 0

    async def _stream():
        nonlocal sent
        for _ in range(1000):
            sent += 256
            yield b"A" * 256

    async with _client(lambda _r: httpx.Response(200, content=_stream())) as client:
        with pytest.raises(ResponseTooLargeError):
            await _get(client)
    # 停在剛越線處,沒有把 256KB 全吃進來
    assert sent <= 1024 + 256


@pytest.mark.asyncio
async def test_charset_still_decoded_after_materialize():
    body = "<html><title>密度</title></html>".encode("utf-8")

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/html; charset=utf-8"}
        )

    async with _client(handler) as client:
        resp = await _get(client)
    assert "密度" in resp.text


@pytest.mark.asyncio
async def test_redirect_target_still_validated_before_request():
    """回歸:改成 stream 之後,轉址仍必須逐跳過 url_policy 才發出下一個請求。"""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/x"})

    async with _client(handler) as client:
        with pytest.raises(PolicyViolationError):
            await _get(client)
    assert requested == [_ALLOWED]


@pytest.mark.asyncio
async def test_allowed_redirect_is_followed_and_body_returned():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/page":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, text="<html><title>final</title></html>")

    async with _client(handler) as client:
        resp = await _get(client)
    assert resp.text == "<html><title>final</title></html>"
    assert requested == [_ALLOWED, "https://market.cloud.edu.tw/final"]
