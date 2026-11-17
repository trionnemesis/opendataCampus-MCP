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


# ── bounded_get 轉址目標護欄(CWE-918 回歸測試)────────────────────────────────


class TestBoundedGetRedirectTarget:
    """safe_get 對每一跳都跑 url_policy;bounded_get 先前對轉址目標完全不檢查。

    觸發條件:允許的固定端點(data.gov.tw / CEEC / TWCampus,三者的 client
    皆為 follow_redirects=True)回一個 Location,httpx 就會跟下去 —— 包含
    scheme 降級與 cloud metadata 等內網位址。
    """

    @staticmethod
    async def _follow(location: str) -> tuple[httpx.Response | None, list[str], Exception | None]:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/start":
                return httpx.Response(302, headers={"Location": location})
            return httpx.Response(
                200, headers={"Content-Type": "text/plain"}, text="REACHED"
            )

        client = httpx.AsyncClient(
            follow_redirects=True, transport=httpx.MockTransport(handler)
        )
        async with client:
            try:
                return (
                    await safe_http.bounded_get(client, "https://twcampus.example.gov.tw/start"),
                    seen,
                    None,
                )
            except Exception as exc:  # noqa: BLE001 — 測試要斷言例外型別
                return None, seen, exc

    @pytest.mark.parametrize(
        "location",
        [
            "http://169.254.169.254/latest/meta-data/",  # scheme 降級 + link-local
            "https://169.254.169.254/latest/meta-data/",  # cloud metadata
            "https://127.0.0.1/admin",                    # loopback
            "https://10.0.0.5/internal",                  # RFC1918
            "https://192.168.1.1/router",
            "https://172.16.0.1/internal",
            "https://[::1]/admin",                        # IPv6 loopback
            "https://localhost/admin",
            "http://twcampus.example.gov.tw/start2",      # 單純 scheme 降級
        ],
    )
    async def test_unsafe_redirect_target_blocked(self, location: str) -> None:
        resp, seen, exc = await self._follow(location)
        assert isinstance(exc, PolicyViolationError), f"應擋下 {location}: {exc!r}"
        # 關鍵斷言:危險的那一跳「從未被發出」,不是發出後才丟棄
        assert seen == ["https://twcampus.example.gov.tw/start"], seen

    @pytest.mark.parametrize(
        "location",
        [
            "/moved",                               # 同站相對路徑
            "https://twcampus.example.gov.tw/moved",  # 同站絕對路徑
            "https://www.data.gov.tw/api/v2/x",       # 跨網域公開 https(CDN 等)
        ],
    )
    async def test_legitimate_redirect_still_followed(self, location: str) -> None:
        """只擋真正造成影響的類別;公開 https 轉址行為不變。"""
        resp, seen, exc = await self._follow(location)
        assert exc is None, f"不應擋下 {location}: {exc!r}"
        assert resp is not None and resp.text == "REACHED"
        assert len(seen) == 2, seen
