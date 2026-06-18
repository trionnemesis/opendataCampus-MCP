"""OpenDataApiAdapter 單元測試 — browse(catalog 離線) + read(httpx.MockTransport)。"""
from __future__ import annotations

import httpx
import pytest

from opendata_campus_mcp.adapters.opendata import OpenDataApiAdapter
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    EducationSource,
    SourceUnavailableError,
)

_SOURCE = EducationSource(
    name="政府資料開放平臺",
    official_url="https://data.gov.tw",
    access_strategy=AccessStrategy.OPEN_DATA,
)


def _read_adapter(handler) -> OpenDataApiAdapter:
    a = OpenDataApiAdapter()
    a._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return a


def _envelope(result: dict, success: bool = True) -> dict:
    return {"success": success, "result": result, "help": ""}


# ── browse（純 catalog，不打 API）─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_browse_filters_catalog_by_keyword():
    a = OpenDataApiAdapter()
    res = await a.browse(_SOURCE, BrowseRequest("政府資料開放平臺", "教師", max_results=3))
    assert res
    assert "教師" in res[0].title  # 9624 大專校院各校科系別專任教師數 命中
    assert res[0].url.startswith("https://data.gov.tw/dataset/")
    assert res[0].source_name == "政府資料開放平臺"
    await a.aclose()


@pytest.mark.asyncio
async def test_browse_no_match_falls_back_to_catalog():
    a = OpenDataApiAdapter()
    res = await a.browse(_SOURCE, BrowseRequest("政府資料開放平臺", "zzz無命中關鍵字", max_results=2))
    assert len(res) == 2  # 無命中 → 退回目錄前 N
    await a.aclose()


@pytest.mark.asyncio
async def test_browse_respects_max_results():
    a = OpenDataApiAdapter()
    res = await a.browse(_SOURCE, BrowseRequest("政府資料開放平臺", "學生", max_results=2))
    assert len(res) <= 2
    await a.aclose()


# ── read（MockTransport）──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_maps_result_with_resources():
    result = {
        "title": "大專校院名錄",
        "description": "全臺灣大專校院通訊資料",
        "dataProvider": "sti571",
        "license": "1",
        "keyword": ["名錄", "大專校院"],
        "distribution": [
            {"resourceFormat": "CSV", "resourceDownloadUrl": "https://stats.moe.gov.tw/x.csv"},
            {"resourceFormat": "JSON", "resourceDownloadUrl": "https://stats.moe.gov.tw/x.json"},
        ],
    }
    a = _read_adapter(lambda r: httpx.Response(200, json=_envelope(result)))
    out = await a.read("https://data.gov.tw/dataset/6091", ["title", "license"])
    assert out["title"] == "大專校院名錄"
    assert out["publisher"] == "教育部統計處"
    assert out["license"] == "政府資料開放授權條款-第1版 (OGDL v1.0)"
    assert out["education_stage"] == "大學"  # 查 catalog（6091）
    assert out["subject"] == "名錄、大專校院"
    assert out["resources"] == [
        {"format": "CSV", "download_url": "https://stats.moe.gov.tw/x.csv"},
        {"format": "JSON", "download_url": "https://stats.moe.gov.tw/x.json"},
    ]


@pytest.mark.asyncio
async def test_read_success_false_raises():
    body = {"success": False, "error": {"error_type": "Not Found", "message": "Not Found"}}
    a = _read_adapter(lambda r: httpx.Response(200, json=body))
    with pytest.raises(SourceUnavailableError):
        await a.read("https://data.gov.tw/dataset/999999999", ["title"])


@pytest.mark.asyncio
async def test_read_no_id_in_url_raises():
    a = _read_adapter(lambda r: httpx.Response(200, json=_envelope({})))
    with pytest.raises(SourceUnavailableError):
        await a.read("https://data.gov.tw/about", ["title"])


@pytest.mark.asyncio
async def test_read_http_500_raises():
    a = _read_adapter(lambda r: httpx.Response(500))
    with pytest.raises(SourceUnavailableError):
        await a.read("https://data.gov.tw/dataset/6091", ["title"])


@pytest.mark.asyncio
async def test_read_transport_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fail")
    a = _read_adapter(handler)
    with pytest.raises(SourceUnavailableError):
        await a.read("https://data.gov.tw/dataset/6091", ["title"])


@pytest.mark.asyncio
async def test_read_catalog_miss_and_license_passthrough():
    # license 非 "1" → 原樣；catalog 外 id → education_stage None；keyword 空 → subject None
    result = {"title": "X", "description": "", "license": "CC BY 4.0", "keyword": [], "distribution": []}
    a = _read_adapter(lambda r: httpx.Response(200, json=_envelope(result)))
    out = await a.read("https://data.gov.tw/dataset/12345", ["license"])
    assert out["license"] == "CC BY 4.0"
    assert out["education_stage"] is None
    assert out["subject"] is None
    assert out["resources"] == []
