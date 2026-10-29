"""EduMarketApiAdapter 單元測試 — 以 httpx.MockTransport 模擬 API（離線、無新依賴）。

涵蓋：信封 → SearchResult 映射、空結果、status:0 / HTTP 錯誤 / 連線錯誤 / 非 JSON
的錯誤對應、keyword path-encode、無 key safety net、read 委派、copyright 不誤映 publisher。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from opendata_campus_mcp.adapters.edumarket import EduMarketApiAdapter
from opendata_campus_mcp.contracts import (
    BrowseRequest,
    EducationSource,
    LoginRequiredError,
    SourceUnavailableError,
)

_SOURCE = EducationSource(
    name="教育大市集",
    official_url="https://market.cloud.edu.tw",
)
_REQ = BrowseRequest(source_name_or_url="教育大市集", query="密度", max_results=5)

_RESOURCE = {
    "id": 123,
    "title": "密度教學教案",
    "url": "https://market.cloud.edu.tw/resource/123",
    "desc": "八年級理化密度單元教案",
    "edugrade": "國中",
    "domain": ["自然科學", "理化"],
    "copyright": "創用CC-姓名標示",
    "contributor": [{"name": "王老師", "org": "臺北市立某國中", "role": "作者"}],
}


def _adapter_with(handler, api_key: str = "test_key") -> EduMarketApiAdapter:
    """建立用 MockTransport 的 adapter（替換私有 client）。"""
    adapter = EduMarketApiAdapter(api_key=api_key)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


def _envelope(resources: list, status: int = 1, msg: str = "") -> dict:
    return {"status": status, "msg": msg, "page": 1, "totalpage": 1, "resources": resources}


@pytest.mark.asyncio
async def test_browse_maps_envelope_to_search_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope([_RESOURCE, dict(_RESOURCE, id=124)]))

    results = await _adapter_with(handler).browse(_SOURCE, _REQ)
    assert len(results) == 2
    r = results[0]
    assert r.title == "密度教學教案"
    assert r.url == "https://market.cloud.edu.tw/resource/123"
    assert r.education_stage == "國中"        # ← edugrade
    assert r.subject == "自然科學、理化"        # ← domain joined
    assert r.publisher == "臺北市立某國中"      # ← contributor[0].org
    assert r.source_name == "教育大市集"
    assert r.source_url == "https://market.cloud.edu.tw"


@pytest.mark.asyncio
async def test_browse_empty_resources_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope([]))

    assert await _adapter_with(handler).browse(_SOURCE, _REQ) == []


@pytest.mark.asyncio
async def test_browse_status_zero_raises_unavailable():
    # 無效 key 常以 HTTP 200 + status:0 回應 → 須當失敗,不可靜默回空
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope([], status=0, msg="invalid key"))

    with pytest.raises(SourceUnavailableError):
        await _adapter_with(handler).browse(_SOURCE, _REQ)


@pytest.mark.asyncio
async def test_browse_http_403_raises_login_required():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(LoginRequiredError):
        await _adapter_with(handler).browse(_SOURCE, _REQ)


@pytest.mark.asyncio
async def test_browse_http_500_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(SourceUnavailableError):
        await _adapter_with(handler).browse(_SOURCE, _REQ)


@pytest.mark.asyncio
async def test_browse_transport_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed")

    with pytest.raises(SourceUnavailableError):
        await _adapter_with(handler).browse(_SOURCE, _REQ)


@pytest.mark.asyncio
async def test_browse_invalid_json_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(SourceUnavailableError):
        await _adapter_with(handler).browse(_SOURCE, _REQ)


@pytest.mark.asyncio
async def test_keyword_is_path_encoded():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_envelope([]))

    req = BrowseRequest(source_name_or_url="教育大市集", query="密度 八年級", max_results=3)
    await _adapter_with(handler).browse(_SOURCE, req)
    assert "/v2/search/edumarket/" in captured["url"]
    assert "%E5%AF%86%E5%BA%A6" in captured["url"]   # 密度（path 內 percent-encode）
    assert "%20" in captured["url"]                   # 空白被 encode,未拆成多段 path
    assert "key=test_key" in captured["url"]
    assert "rows=3" in captured["url"]


@pytest.mark.asyncio
async def test_no_key_raises_unavailable(monkeypatch):
    monkeypatch.delenv("EDUMARKET_API_KEY", raising=False)
    adapter = EduMarketApiAdapter(api_key=None)
    with pytest.raises(SourceUnavailableError):
        await adapter.browse(_SOURCE, _REQ)


@pytest.mark.asyncio
async def test_read_delegates_to_html_reader():
    reader = AsyncMock()
    reader.read.return_value = {"url": "u", "title": "t"}
    adapter = EduMarketApiAdapter(api_key="k", html_reader=reader)
    out = await adapter.read("https://market.cloud.edu.tw/resource/1", ["title"])
    reader.read.assert_awaited_once_with("https://market.cloud.edu.tw/resource/1", ["title"])
    assert out["title"] == "t"


@pytest.mark.asyncio
async def test_copyright_not_mapped_to_publisher():
    # 有 copyright 但無 contributor → publisher 為 None（copyright 是授權,非出版者）
    item = {"title": "x", "url": "u", "desc": "d", "copyright": "創用CC-姓名標示"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope([item]))

    results = await _adapter_with(handler).browse(_SOURCE, _REQ)
    assert results[0].publisher is None


# ── 安全回歸:API key 不得隨跳轉外洩(CWE-200 / CWE-598)──────────────────────


@pytest.mark.asyncio
async def test_browse_does_not_follow_redirects_with_key():
    """3xx 不得被跟隨 —— 否則帶 key 的 URL 會被原樣送往 Location 主機。"""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "market.cloud.edu.tw":
            return httpx.Response(
                302, headers={"Location": "https://evil.example.com/collect"}
            )
        return httpx.Response(200, json=_envelope([_RESOURCE]))

    adapter = EduMarketApiAdapter(api_key="s3cret_key")
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )

    with pytest.raises(SourceUnavailableError):
        await adapter.browse(_SOURCE, _REQ)

    # 只打了官方主機一次,evil.example.com 完全沒收到請求
    assert len(seen) == 1
    assert "market.cloud.edu.tw" in seen[0]
    assert not any("evil.example.com" in u for u in seen)


@pytest.mark.asyncio
async def test_production_client_has_redirects_disabled():
    """預設(非測試注入)client 必須關閉 follow_redirects。"""
    adapter = EduMarketApiAdapter(api_key="s3cret_key")
    try:
        assert adapter._client.follow_redirects is False
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_api_key_is_url_encoded_not_interpolated():
    """key 含 & / # 時必須被 percent-encode,不得切斷 query 或截斷 URL。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_envelope([_RESOURCE]))

    await _adapter_with(handler, api_key="k&page=99#x").browse(_SOURCE, _REQ)

    req = seen[0]
    # key 完整送達(httpx 解碼後仍是原字串),且 page 未被攻擊字串覆寫
    assert req.url.params["key"] == "k&page=99#x"
    assert req.url.params["page"] == "1"
    # raw query 中的 & / # 已被編碼,fragment 未被提前切出
    assert "k%26page%3D99%23x" in str(req.url)
    assert req.url.fragment == ""


@pytest.mark.asyncio
async def test_api_key_never_appears_in_debug_log(caplog):
    """log 只記 path 與 keyword,絕不記 key(CWE-532)。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope([_RESOURCE]))

    with caplog.at_level("DEBUG", logger="opendata_campus_mcp.adapters.edumarket"):
        await _adapter_with(handler, api_key="s3cret_key").browse(_SOURCE, _REQ)

    assert "s3cret_key" not in caplog.text


@pytest.mark.asyncio
async def test_encoded_key_and_bounded_gzip_response_work_together():
    import gzip
    import json

    key = "k&page=99#x"
    payload = json.dumps(_envelope([_RESOURCE])).encode()

    async def body():
        yield gzip.compress(payload)

    def handler(request):
        assert request.url.params["key"] == key
        assert request.url.params["page"] == "1"
        assert request.url.params["rows"] == str(_REQ.max_results)
        return httpx.Response(200, content=body(), headers={
            "Content-Type": "application/json", "Content-Encoding": "gzip",
        })

    adapter = _adapter_with(handler, api_key=key)
    try:
        results = await adapter.browse(_SOURCE, _REQ)
        assert len(results) == 1
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_redirect_is_not_followed_even_with_injected_redirecting_client():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/collect"})

    adapter = EduMarketApiAdapter(api_key="test-secret")
    await adapter._client.aclose()
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    try:
        with pytest.raises(SourceUnavailableError, match="unexpected redirect"):
            await adapter.browse(_SOURCE, _REQ)
        assert len(seen) == 1
        assert seen[0].url.host == "market.cloud.edu.tw"
    finally:
        await adapter.aclose()
