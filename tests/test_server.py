from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import Any

import httpx
import pytest

from opendata_campus_mcp.contracts import AccessStrategy, RateLimitError
from opendata_campus_mcp.mcp_server import runtime as runtime_module
from opendata_campus_mcp.mcp_server import server as server_module


class _RateLimitedWebAdapter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def browse(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise RateLimitError("rate limit")

    async def read(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RateLimitError("rate limit")

    async def aclose(self) -> None:
        pass


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
    monkeypatch.setattr(runtime_module, "WebSearchAdapter", _RateLimitedWebAdapter)
    mcp = server_module.build_server()

    async with mcp._lifespan_manager():
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
    captured: dict[str, Any] = {}
    real_build_runtime = runtime_module.build_runtime

    def capture_runtime() -> Any:
        runtime = real_build_runtime()
        captured["runtime"] = runtime
        return runtime

    monkeypatch.setattr(server_module, "build_runtime", capture_runtime)
    mcp = server_module.build_server()
    runtime = captured["runtime"]
    official_api = runtime.adapters[AccessStrategy.OFFICIAL_API]
    http_get = AsyncMock(side_effect=AssertionError("no-key request must stop before HTTP"))
    official_api._client.get = http_get

    try:
        result = await mcp.call_tool(
            "browse_education_source", {"source": "教育大市集", "query": "數學"}
        )
    finally:
        await runtime.aclose()

    assert result.structured_content == {
        "error": "source_unavailable",
        "source": "教育大市集",
        "url": "https://market.cloud.edu.tw",
        "message": "教育大市集 (https://market.cloud.edu.tw): EDUMARKET_API_KEY not configured",
    }


def test_build_server_uses_shared_runtime_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_build_runtime() -> Any:
        nonlocal calls
        calls += 1
        return SimpleNamespace(service=SimpleNamespace(), aclose=AsyncMock())

    monkeypatch.setattr(server_module, "build_runtime", fake_build_runtime, raising=False)

    server_module.build_server()

    assert calls == 1


@pytest.mark.asyncio
async def test_build_server_closes_runtime_on_lifespan_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_runtime = AsyncMock()
    runtime = SimpleNamespace(service=SimpleNamespace(), aclose=close_runtime)
    monkeypatch.setattr(server_module, "build_runtime", lambda: runtime)

    mcp = server_module.build_server()

    async with mcp._lifespan_manager():
        close_runtime.assert_not_awaited()

    close_runtime.assert_awaited_once()


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("browse_education_source", {"source": "因材網", "query": "數學"}),
        ("read_education_resource", {"url": "https://adl.edu.tw/resource/1"}),
    ],
)
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [(401, "login_required"), (403, "login_required"),
     (404, "source_unavailable"), (503, "source_unavailable")],
)
async def test_web_tools_preserve_json_http_error_classification(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict[str, Any],
    status_code: int,
    expected_error: str,
) -> None:
    """JSON error bodies must reach the existing status-based MCP error mapping."""
    monkeypatch.delenv("EDUMARKET_API_KEY", raising=False)
    real_web_adapter = runtime_module.WebSearchAdapter

    def build_web_adapter(**kwargs: Any) -> Any:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status_code, json={"detail": "denied"})
            )
        )
        return real_web_adapter(client=client, **kwargs)

    monkeypatch.setattr(runtime_module, "WebSearchAdapter", build_web_adapter)
    mcp = server_module.build_server()
    async with mcp._lifespan_manager():
        result = await mcp.call_tool(tool_name, arguments)

    assert result.structured_content["error"] == expected_error
