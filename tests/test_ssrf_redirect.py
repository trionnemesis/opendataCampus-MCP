"""Security regression — outbound redirects must be validated per hop (CWE-918).

在此修正前,ceec_exam / edumarket / opendata / twcampus 四個 adapter 各自以
`httpx.AsyncClient(follow_redirects=True)` 直接送出請求,跳轉目標完全繞過
`PublicEducationUrlPolicy`;上游站台(或中間人)只要回一個 302,就能讓 MCP
伺服器去抓 169.254.169.254 之類的內網位址並把內容回給呼叫端。
"""
from __future__ import annotations

import httpx
import pytest

from opendata_campus_mcp.adapters.ceec_exam import CeecExamAdapter
from opendata_campus_mcp.adapters.edumarket import EduMarketApiAdapter
from opendata_campus_mcp.adapters.opendata import OpenDataApiAdapter
from opendata_campus_mcp.adapters.safe_http import (
    _MAX_REDIRECTS,
    safe_get_fixed_host,
)
from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_METADATA = "http://169.254.169.254/latest/meta-data/iam/"


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )


def _all_adapters():
    return [
        CeecExamAdapter(BrowserPolicy()),
        TwCampusDirectoryAdapter(BrowserPolicy()),
        OpenDataApiAdapter(),
        EduMarketApiAdapter(api_key="test-key"),
    ]


# ── 佈線:四個 adapter 都不得再讓 httpx 自行跟進跳轉 ──────────────────────────


@pytest.mark.parametrize("adapter", _all_adapters(), ids=lambda a: type(a).__name__)
def test_adapter_does_not_auto_follow_redirects(adapter) -> None:
    assert adapter._client.follow_redirects is False
    assert isinstance(adapter._url_policy, PublicEducationUrlPolicy)


# ── 行為:跨主機跳轉必須在送出前被擋下 ────────────────────────────────────────


async def test_offsite_redirect_is_blocked_and_never_requested() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "www.ceec.edu.tw":
            return httpx.Response(302, headers={"Location": _METADATA})
        return httpx.Response(200, text="INTERNAL METADATA CONTENT")

    adapter = CeecExamAdapter(BrowserPolicy())
    adapter._client = _mock_client(handler)

    with pytest.raises(PolicyViolationError):
        await adapter._fetch("https://www.ceec.edu.tw/xmfile?xsmsid=X&page=1")

    assert requested == ["https://www.ceec.edu.tw/xmfile?xsmsid=X&page=1"]
    assert _METADATA not in requested


async def test_opendata_offsite_redirect_is_blocked() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "data.gov.tw":
            return httpx.Response(302, headers={"Location": _METADATA})
        return httpx.Response(200, json={"success": True})

    adapter = OpenDataApiAdapter()
    adapter._client = _mock_client(handler)

    with pytest.raises(PolicyViolationError):
        await adapter.read("https://data.gov.tw/dataset/12345", [])

    assert _METADATA not in requested


# ── 相容性:同主機跳轉仍須正常跟進 ────────────────────────────────────────────


async def test_same_host_redirect_is_still_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/xmfile":
            return httpx.Response(
                301, headers={"Location": "https://www.ceec.edu.tw/moved"}
            )
        return httpx.Response(200, text="LISTING HTML")

    adapter = CeecExamAdapter(BrowserPolicy())
    adapter._client = _mock_client(handler)

    body = await adapter._fetch("https://www.ceec.edu.tw/xmfile?xsmsid=X&page=1")
    assert body == "LISTING HTML"


# ── 資源:跳轉迴圈必須有界 ────────────────────────────────────────────────────


async def test_redirect_loop_is_bounded() -> None:
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://twcampus.org/next"})

    policy = PublicEducationUrlPolicy(["twcampus.org"])
    with pytest.raises(PolicyViolationError, match="redirect limit"):
        await safe_get_fixed_host(
            _mock_client(handler), "https://twcampus.org/", url_policy=policy
        )

    assert len(hops) == _MAX_REDIRECTS + 1


# ── 政策本身:降級為 http、IP literal 皆須拒絕 ────────────────────────────────


@pytest.mark.parametrize(
    "target",
    [
        "http://www.ceec.edu.tw/plain",  # HTTPS → HTTP 降級
        "https://169.254.169.254/",  # IP literal
        "https://evil.example.com/",  # 目錄外主機
    ],
)
async def test_policy_rejects_unsafe_redirect_targets(target: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.ceec.edu.tw" and request.url.scheme == "https":
            return httpx.Response(302, headers={"Location": target})
        raise AssertionError(f"must not request {request.url}")

    policy = PublicEducationUrlPolicy(["www.ceec.edu.tw"])
    with pytest.raises(PolicyViolationError):
        await safe_get_fixed_host(
            _mock_client(handler),
            "https://www.ceec.edu.tw/start",
            url_policy=policy,
        )
