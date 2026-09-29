"""固定端點 adapter 的 redirect 邊界回歸測試(security_best_practices_report SEC-3)。

修正前:ceec/opendata/edumarket/twcampus 各自以 follow_redirects=True 建 client,
上游 open redirect 即可把請求導向 localhost / 雲端 metadata。
修正後:四者皆走 safe_http.safe_get,每一跳送出前先過 url_policy。

每個測試都斷言「惡意目標從未被請求」,而非只斷言拋出例外 —— 後者無法區分
「攔在請求前」與「請求後才失敗」。
"""
from __future__ import annotations

import httpx
import pytest

from opendata_campus_mcp.adapters.ceec_exam import CeecExamAdapter
from opendata_campus_mcp.adapters.edumarket import EduMarketApiAdapter
from opendata_campus_mcp.adapters.opendata import OpenDataApiAdapter
from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    EducationSource,
    ExamSearchRequest,
    PolicyViolationError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy

INTERNAL = "http://169.254.169.254/latest/meta-data/"


def _redirecting_client(requested: list[str]) -> httpx.AsyncClient:
    """第一次請求回 302 指向雲端 metadata;之後的請求一律記錄下來。"""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url == INTERNAL:
            return httpx.Response(200, text="LEAKED-CREDENTIALS")
        return httpx.Response(302, headers={"Location": INTERNAL})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_ceec_does_not_follow_redirect_to_metadata():
    requested: list[str] = []
    adapter = CeecExamAdapter(BrowserPolicy())
    adapter._client = _redirecting_client(requested)

    with pytest.raises(PolicyViolationError):
        await adapter.search(ExamSearchRequest(exam_type="學測", max_results=1))

    assert INTERNAL not in requested


async def test_opendata_does_not_follow_redirect_to_metadata():
    requested: list[str] = []
    adapter = OpenDataApiAdapter()
    adapter._client = _redirecting_client(requested)

    with pytest.raises(PolicyViolationError):
        await adapter.read("https://data.gov.tw/dataset/12345", [])

    assert INTERNAL not in requested


async def test_edumarket_does_not_follow_redirect_to_metadata():
    requested: list[str] = []
    adapter = EduMarketApiAdapter(api_key="test_key")
    adapter._client = _redirecting_client(requested)
    source = EducationSource(
        name="教育大市集",
        description="",
        official_url="https://market.cloud.edu.tw",
        education_stages=(),
        categories=(),
        directory_source="",
        access_strategy=AccessStrategy.OFFICIAL_API,
    )

    with pytest.raises(PolicyViolationError):
        await adapter.browse(source, BrowseRequest(source_name_or_url="教育大市集", query="數學"))

    assert INTERNAL not in requested


async def test_twcampus_degrades_instead_of_following_redirect():
    """目錄補充的契約是「任何失敗都降級」,故回空列表而非拋例外 —— 但不得發出請求。"""
    from opendata_campus_mcp.contracts import DiscoveryRequest

    requested: list[str] = []
    adapter = TwCampusDirectoryAdapter(BrowserPolicy())
    adapter._client = _redirecting_client(requested)

    result = await adapter.discover(DiscoveryRequest(query="數學"))

    assert result == []
    assert INTERNAL not in requested


async def test_all_fixed_endpoint_clients_disable_automatic_redirects():
    """回歸守門:任何新 adapter 若把 follow_redirects 打開,此測試即失敗。"""
    adapters = [
        CeecExamAdapter(BrowserPolicy()),
        OpenDataApiAdapter(),
        EduMarketApiAdapter(api_key="k"),
        TwCampusDirectoryAdapter(BrowserPolicy()),
    ]
    for adapter in adapters:
        assert adapter._client.follow_redirects is False, type(adapter).__name__
