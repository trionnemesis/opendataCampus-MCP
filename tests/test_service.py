"""整合測試：EdBrowserService 核心三工具（mock 隔離網路）。

對應 spec/features/ 全部 5 個 feature 的 service 層驗證。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from opendata_campus_mcp.contracts import (
    BrowseRequest,
    DiscoveryRequest,
    EducationSource,
    LoginRequiredError,
    ReadRequest,
    SearchResult,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.mcp_server.service import EdBrowserService
from opendata_campus_mcp.repository.source_cache import get_known_sources


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def policy() -> BrowserPolicy:
    return BrowserPolicy()


@pytest.fixture()
def router() -> SourceRouter:
    return SourceRouter(get_known_sources())


@pytest.fixture()
def mock_twcampus() -> AsyncMock:
    m = AsyncMock()
    m.discover.return_value = []
    return m


@pytest.fixture()
def mock_web() -> AsyncMock:
    m = AsyncMock()
    m.browse.return_value = [
        SearchResult(
            title="密度教學教案",
            url="https://market.cloud.edu.tw/resource/123",
            summary="八年級理化密度單元教案，含實驗設計",
            source_name="教育大市集",
            source_url="https://market.cloud.edu.tw",
        )
    ]
    m.read.return_value = {
        "url": "https://market.cloud.edu.tw/resource/123",
        "title": "密度教學教案",
        "summary": "八年級理化密度單元教案，含實驗設計",
        "publisher": "教育大市集",
        "education_stage": None,
        "subject": None,
        "license": None,
    }
    return m


@pytest.fixture()
def service(policy: BrowserPolicy, router: SourceRouter, mock_twcampus: AsyncMock, mock_web: AsyncMock) -> EdBrowserService:
    return EdBrowserService(policy, router, mock_twcampus, mock_web)


# ── discover_education_sources ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_returns_list_within_max(service: EdBrowserService):
    req = DiscoveryRequest(query="教案 國中", max_sources=3)
    result = await service.discover_sources(req)
    assert isinstance(result, list)
    assert len(result) <= 3


@pytest.mark.asyncio
async def test_discover_result_has_required_fields(service: EdBrowserService):
    req = DiscoveryRequest(query="教案", max_sources=2)
    result = await service.discover_sources(req)
    for item in result:
        assert "official_url" in item
        assert "directory_source" in item
        assert "name" in item


@pytest.mark.asyncio
async def test_discover_stage_filter(service: EdBrowserService):
    req = DiscoveryRequest(query="教材", education_stage="大學", max_sources=5)
    result = await service.discover_sources(req)
    # 所有回傳平台的 education_stages 應包含「大學」或為空（無限制）
    for item in result:
        stages = item.get("education_stages", [])
        assert not stages or "大學" in stages or "全階段" in stages


@pytest.mark.asyncio
async def test_discover_falls_back_to_twcampus_when_insufficient(
    policy: BrowserPolicy,
    router: SourceRouter,
    mock_web: AsyncMock,
):
    live_source = EducationSource(
        name="測試平台",
        official_url="https://test.edu.tw",
        description="從 TWCampus 發現",
        directory_source="TWCampus",
    )
    mock_twcampus = AsyncMock()
    mock_twcampus.discover.return_value = [live_source]

    svc = EdBrowserService(policy, router, mock_twcampus, mock_web)
    req = DiscoveryRequest(query="zzz_no_local_match", max_sources=3)
    await svc.discover_sources(req)

    # 本地無正分 → 應補充呼叫 TWCampus
    mock_twcampus.discover.assert_called_once()


@pytest.mark.asyncio
async def test_discover_twcampus_error_degrades_gracefully(service: EdBrowserService, mock_twcampus: AsyncMock):
    mock_twcampus.discover.side_effect = ConnectionError("network error")
    req = DiscoveryRequest(query="教案", max_sources=3)
    # 不應拋出；應降級至本地快取
    result = await service.discover_sources(req)
    assert isinstance(result, list)


# ── browse_education_source ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_browse_returns_results_with_source_fields(service: EdBrowserService):
    req = BrowseRequest(source_name_or_url="教育大市集", query="密度", max_results=5)
    result = await service.browse_source(req)
    assert "results" in result
    assert "official_url" in result
    for r in result["results"]:
        assert r["source_name"]
        assert r["source_url"]


@pytest.mark.asyncio
async def test_browse_unknown_source_builds_adhoc(service: EdBrowserService, mock_web: AsyncMock):
    mock_web.browse.return_value = []
    req = BrowseRequest(source_name_or_url="https://unknown.edu.tw", query="教材", max_results=5)
    result = await service.browse_source(req)
    assert result["official_url"] == "https://unknown.edu.tw"


@pytest.mark.asyncio
async def test_browse_source_unavailable_propagates(service: EdBrowserService, mock_web: AsyncMock):
    mock_web.browse.side_effect = SourceUnavailableError("教育大市集", "https://market.cloud.edu.tw", "timeout")
    req = BrowseRequest(source_name_or_url="教育大市集", query="教材", max_results=5)
    with pytest.raises(SourceUnavailableError):
        await service.browse_source(req)


# ── read_education_resource ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_returns_url_field_matching_input(service: EdBrowserService):
    url = "https://market.cloud.edu.tw/resource/123"
    req = ReadRequest(url=url)
    result = await service.read_resource(req)
    assert result["url"] == url


@pytest.mark.asyncio
async def test_read_login_required_propagates(service: EdBrowserService, mock_web: AsyncMock):
    mock_web.read.side_effect = LoginRequiredError("login required")
    req = ReadRequest(url="https://private.edu.tw/resource/1")
    with pytest.raises(LoginRequiredError):
        await service.read_resource(req)
