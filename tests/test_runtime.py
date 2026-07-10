from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from opendata_campus_mcp.contracts import AccessStrategy
from opendata_campus_mcp.mcp_server.runtime import Runtime, build_runtime
from opendata_campus_mcp.repository.source_cache import get_known_sources


@pytest.mark.asyncio
async def test_build_runtime_registers_all_supported_browse_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EDUMARKET_API_KEY", raising=False)
    runtime = build_runtime()

    try:
        required_strategies = {
            source.access_strategy for source in get_known_sources().values()
        }
        assert required_strategies <= set(runtime.adapters)
        assert {
            AccessStrategy.WEB_SEARCH,
            AccessStrategy.OFFICIAL_API,
            AccessStrategy.OPEN_DATA,
        } <= set(runtime.adapters)
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_runtime_aclose_closes_each_owned_resource_once() -> None:
    first = SimpleNamespace(aclose=AsyncMock())
    second = SimpleNamespace(aclose=AsyncMock())
    runtime = Runtime(
        service=SimpleNamespace(),
        adapters={},
        closeables=(first, second),
    )

    await runtime.aclose()

    first.aclose.assert_awaited_once()
    second.aclose.assert_awaited_once()
