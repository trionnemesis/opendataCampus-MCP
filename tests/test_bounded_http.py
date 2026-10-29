"""Offline regressions for the shared fixed-endpoint response boundary."""
import gzip

import httpx
import pytest

from opendata_campus_mcp.adapters import safe_http
from opendata_campus_mcp.contracts import PolicyViolationError


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("status", [200, 403, 503])
@pytest.mark.parametrize("declared", [False, True])
async def test_bounded_get_stops_and_closes_oversized_stream(status, declared):
    stream = TrackedStream([b"1234", b"5", b"never read"])
    headers = {"Content-Type": "application/json"}
    if declared:
        headers["Content-Length"] = "5"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, headers=headers, stream=stream)
    )) as client:
        with pytest.raises(PolicyViolationError, match="exceeds"):
            await safe_http.bounded_get(client, "https://example.edu.tw", max_bytes=4)
    assert stream.reads == (0 if declared else 2)
    assert stream.closed


@pytest.mark.parametrize("status", [200, 403, 503])
async def test_bounded_get_decodes_gzip_once_and_preserves_status(status):
    payload = b'{"value":"compressed response"}'
    compressed = gzip.compress(payload)
    stream = TrackedStream([compressed])
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, stream=stream, headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "Content-Length": str(len(compressed)),
            "X-Trace": "retained",
        })
    )) as client:
        response = await safe_http.bounded_get(client, "https://example.edu.tw")
    assert response.status_code == status
    assert response.content == payload
    assert response.json() == {"value": "compressed response"}
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(payload))
    assert response.headers["x-trace"] == "retained"
    assert stream.closed


async def test_bounded_get_caps_decoded_gzip_bytes():
    stream = TrackedStream([gzip.compress(b"x" * 4096)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream, headers={
            "Content-Type": "text/html", "Content-Encoding": "gzip",
        })
    )) as client:
        with pytest.raises(PolicyViolationError, match="exceeds"):
            await safe_http.bounded_get(client, "https://example.edu.tw", max_bytes=128)
    assert stream.closed


async def test_automatic_redirect_body_is_never_buffered():
    redirect_stream = TrackedStream([b"x" * 1024])
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, stream=redirect_stream, headers={
                "Location": "/final", "Content-Length": "1024",
            })
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True,
    ) as client:
        response = await safe_http.bounded_get(
            client, "https://example.edu.tw/start", max_bytes=4
        )
    assert response.text == "ok"
    assert response.request.url.path == "/final"
    assert len(seen) == 2
    assert redirect_stream.reads == 0
    assert redirect_stream.closed


async def test_redirect_loop_retains_client_hop_limit():
    streams = []

    def handler(request):
        stream = TrackedStream([b"unread"])
        streams.append(stream)
        return httpx.Response(302, stream=stream, headers={"Location": "/loop"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True, max_redirects=2,
    ) as client:
        with pytest.raises(httpx.TooManyRedirects):
            await safe_http.bounded_get(client, "https://example.edu.tw/loop")
    assert len(streams) == 3
    assert all(s.closed and s.reads == 0 for s in streams)
