from __future__ import annotations

from typing import Any

import pytest

from opendata_campus_mcp.contracts import RateLimitError, SourceUnavailableError
from opendata_campus_mcp.mcp_server import server as server_module


class _RateLimitedWebAdapter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def browse(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise RateLimitError("rate limit")

    async def read(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RateLimitError("rate limit")


class _UnexpectedWebAdapter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def browse(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("web fallback must not run")

    async def read(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("web fallback must not run")


class _NoKeyEduMarketAdapter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def browse(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise SourceUnavailableError(
            "教育大市集", "https://market.cloud.edu.tw", "EDUMARKET_API_KEY not configured"
        )

    async def read(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("read is not part of this regression")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "browse_education_source",
            {"source": "因材網", "query": "數學"},
        ),
        (
            "read_education_resource",
            {"url": "https://market.cloud.edu.tw/resource/1"},
        ),
    ],
)
async def test_generic_web_tools_return_structured_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    monkeypatch.delenv("EDUMARKET_API_KEY", raising=False)
    monkeypatch.setattr(server_module, "WebSearchAdapter", _RateLimitedWebAdapter)
    mcp = server_module.build_server()

    result = await mcp.call_tool(tool_name, arguments)

    assert result.structured_content == {
        "error": "rate_limited",
        "message": "rate limit",
    }


@pytest.mark.asyncio
async def test_no_key_market_browse_returns_structured_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EDUMARKET_API_KEY", raising=False)
    monkeypatch.setattr(server_module, "WebSearchAdapter", _UnexpectedWebAdapter)
    monkeypatch.setattr(server_module, "EduMarketApiAdapter", _NoKeyEduMarketAdapter)
    mcp = server_module.build_server()

    result = await mcp.call_tool(
        "browse_education_source", {"source": "教育大市集", "query": "數學"}
    )

    assert result.structured_content == {
        "error": "source_unavailable",
        "source": "教育大市集",
        "url": "https://market.cloud.edu.tw",
        "message": "教育大市集 (https://market.cloud.edu.tw): EDUMARKET_API_KEY not configured",
    }
