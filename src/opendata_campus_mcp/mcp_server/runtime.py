"""Shared adapter assembly for MCP and maintenance entry points."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from opendata_campus_mcp.adapters.ceec_exam import CeecExamAdapter
from opendata_campus_mcp.adapters.edumarket import EduMarketApiAdapter
from opendata_campus_mcp.adapters.opendata import OpenDataApiAdapter
from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.adapters.web_search import WebSearchAdapter
from opendata_campus_mcp.contracts import AccessStrategy, BrowseAdapter
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.mcp_server.service import EdBrowserService
from opendata_campus_mcp.repository.source_cache import get_known_sources


class AsyncCloseable(Protocol):
    async def aclose(self) -> None: ...


@dataclass
class Runtime:
    """Runtime-owned service, adapters, and client cleanup."""

    service: EdBrowserService
    adapters: dict[AccessStrategy, BrowseAdapter]
    closeables: tuple[AsyncCloseable, ...]

    async def aclose(self) -> None:
        for closeable in self.closeables:
            await closeable.aclose()


def build_runtime() -> Runtime:
    """Build the production adapter registry used by every entry point."""
    policy = BrowserPolicy()
    known_sources = get_known_sources()
    router = SourceRouter(known_sources)
    url_policy = PublicEducationUrlPolicy.from_sources(known_sources.values())
    twcampus = TwCampusDirectoryAdapter(policy)
    web = WebSearchAdapter(policy=policy, url_policy=url_policy)
    edumarket = EduMarketApiAdapter(html_reader=web)
    opendata = OpenDataApiAdapter()
    exam = CeecExamAdapter(policy)
    adapters: dict[AccessStrategy, BrowseAdapter] = {
        AccessStrategy.WEB_SEARCH: web,
        AccessStrategy.OFFICIAL_API: edumarket,
        AccessStrategy.OPEN_DATA: opendata,
    }
    service = EdBrowserService(
        policy,
        router,
        twcampus,
        adapters,
        fallback=web,
        exam_adapter=exam,
        url_policy=url_policy,
    )
    return Runtime(
        service=service,
        adapters=adapters,
        closeables=(twcampus, web, edumarket, opendata, exam),
    )
