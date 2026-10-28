"""safe_get 的回應大小與 Content-Type 護欄(SEC-4 回歸測試)。

全離線:以 httpx.MockTransport 合成回應,絕不連外網。
大小上限以 monkeypatch 調小,避免在測試中配置真的 5MB。
"""
from __future__ import annotations

import gzip

import httpx
import pytest

from opendata_campus_mcp.adapters import safe_http
from opendata_campus_mcp.adapters.safe_http import safe_get
from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_URL = "https://example.edu.tw/resource/1"


def _policies() -> tuple[PublicEducationUrlPolicy, BrowserPolicy]:
    return PublicEducationUrlPolicy(["example.edu.tw"]), BrowserPolicy()


async def _get(handler) -> httpx.Response:
    url_policy, browser_policy = _policies()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return await safe_get(
        client, _URL, url_policy=url_policy, browser_policy=browser_policy
    )


# ── 大小上限 ────────────────────────────────────────────────────────────────


async def test_oversized_body_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(safe_http, "MAX_RESPONSE_BYTES", 1024)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x" * 4096, headers={"Content-Type": "text/html"}
        )

    with pytest.raises(PolicyViolationError, match="exceeds"):
        await _get(handler)


async def test_declared_content_length_over_limit_is_rejected(monkeypatch) -> None:
    """宣告的 Content-Length 超量時直接拒絕,不應開始讀取 body。"""
    monkeypatch.setattr(safe_http, "MAX_RESPONSE_BYTES", 1024)
    streamed = {"hit": False}

    async def iter_body():
        streamed["hit"] = True
        yield b"x" * 4096

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=iter_body(),
            headers={"Content-Type": "text/html", "Content-Length": "4096"},
        )

    with pytest.raises(PolicyViolationError, match="declared"):
        await _get(handler)
    assert streamed["hit"] is False


async def test_body_exactly_at_limit_is_allowed(monkeypatch) -> None:
    """邊界:正好等於上限不得誤殺。"""
    monkeypatch.setattr(safe_http, "MAX_RESPONSE_BYTES", 1024)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x" * 1024, headers={"Content-Type": "text/html"}
        )

    resp = await _get(handler)
    assert len(resp.content) == 1024


# ── Content-Type 白名單 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "media_type",
    ["image/png", "application/octet-stream", "application/pdf", "video/mp4",
     "application/json"],
)
async def test_non_text_content_type_is_rejected(media_type: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x00\x01", headers={"Content-Type": media_type})

    with pytest.raises(PolicyViolationError, match="content type"):
        await _get(handler)


@pytest.mark.parametrize(
    "header",
    ["text/html; charset=utf-8", "TEXT/HTML", "application/xhtml+xml", "text/plain"],
)
async def test_allowed_content_types_pass(header: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html><title>ok</title></html>", headers={"Content-Type": header}
        )

    resp = await _get(handler)
    assert resp.status_code == 200
    assert "ok" in resp.text


async def test_missing_content_type_is_still_allowed() -> None:
    """部分政府教育站台不回 Content-Type — 既有行為須保留(缺標頭不阻擋)。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><title>ok</title></html>")

    resp = await _get(handler)
    assert "ok" in resp.text


# ── 回傳介面不變(呼叫端無需改動)────────────────────────────────────────────


async def test_returned_response_preserves_text_status_and_headers() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><title>標題</title></html>",
            headers={"Content-Type": "text/html; charset=utf-8", "X-Trace": "abc"},
        )

    resp = await _get(handler)
    assert resp.status_code == 200
    assert "標題" in resp.text          # 解碼行為不變
    assert resp.headers["X-Trace"] == "abc"  # 非 transfer 標頭保留


async def test_gzip_body_is_not_double_decoded() -> None:
    """aiter_bytes 已解碼;重建回應時必須移除 Content-Encoding 避免二次解碼。"""
    payload = b"<html><title>gz</title></html>"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(payload),
            headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        )

    resp = await _get(handler)
    assert "gz" in resp.text


async def test_error_status_body_is_still_returned() -> None:
    """4xx/5xx 仍需回到呼叫端做狀態碼分支(login required / unavailable)。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied", headers={"Content-Type": "text/html"})

    resp = await _get(handler)
    assert resp.status_code == 403


@pytest.mark.parametrize("status_code", [403, 503])
@pytest.mark.parametrize("scenario", ["within_limit", "declared_limit", "stream_limit"])
async def test_json_error_stream_is_bounded_and_closed(
    monkeypatch, status_code: int, scenario: str
) -> None:
    monkeypatch.setattr(safe_http, "MAX_RESPONSE_BYTES", 4)

    class TrackedStream(httpx.AsyncByteStream):
        chunks_read = 0
        closed = False

        async def __aiter__(self):
            chunks = [b"{}"] if scenario == "within_limit" else [b"aaaa", b"b", b"unread"]
            for chunk in chunks:
                self.chunks_read += 1
                yield chunk

        async def aclose(self):
            self.closed = True

    stream = TrackedStream()
    headers = {"Content-Type": "application/json"}
    if scenario == "declared_limit":
        headers["Content-Length"] = "5"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, headers=headers, stream=stream)
        )
    ) as client:
        url_policy, browser_policy = _policies()
        if scenario == "within_limit":
            response = await safe_get(
                client, _URL, url_policy=url_policy, browser_policy=browser_policy
            )
            assert response.status_code == status_code
            assert response.json() == {}
            assert stream.chunks_read == 1
        else:
            with pytest.raises(PolicyViolationError, match="exceeds"):
                await safe_get(
                    client, _URL, url_policy=url_policy, browser_policy=browser_policy
                )
            assert stream.chunks_read == (0 if scenario == "declared_limit" else 2)
        assert stream.closed


# ── 與既有護欄並存 ──────────────────────────────────────────────────────────


async def test_redirect_to_disallowed_host_still_blocked_before_request() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/x"})

    with pytest.raises(PolicyViolationError):
        await _get(handler)
    assert requested == [_URL]  # 第二次請求從未發出


async def test_allowed_relative_redirect_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/resource/1":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(
            200, text="<html><title>final</title></html>",
            headers={"Content-Type": "text/html"},
        )

    resp = await _get(handler)
    assert "final" in resp.text
