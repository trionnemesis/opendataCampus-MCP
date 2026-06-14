"""EdBrowserService — 業務邏輯協調層。

orchestrate discover / browse / read 三個 MCP 工具的核心流程：
  discover_sources → 本地快取優先 → 不足時補充 TWCampus → 合併去重
  browse_source    → 解析平台 → WebSearchAdapter
  read_resource    → WebSearchAdapter.read
"""
from __future__ import annotations

import logging
from typing import Any

from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.adapters.web_search import WebSearchAdapter
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    DiscoveryRequest,
    EducationSource,
    ReadRequest,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.repository.source_cache import get_known_sources

log = logging.getLogger(__name__)


class EdBrowserService:
    def __init__(
        self,
        policy: BrowserPolicy,
        router: SourceRouter,
        twcampus: TwCampusDirectoryAdapter,
        web: WebSearchAdapter,
    ) -> None:
        self._policy = policy
        self._router = router
        self._twcampus = twcampus
        self._web = web

    # ── discover_education_sources ────────────────────────────────────────────

    async def discover_sources(self, request: DiscoveryRequest) -> list[dict[str, Any]]:
        known = list(get_known_sources().values())
        ranked = self._router.score_sources(known, request)  # [(score, source)]

        # 取正分（有關鍵字命中）的平台
        positive: list[EducationSource] = [s for sc, s in ranked if sc > 0]

        # 本地正分不足 → 補充 TWCampus（任何錯誤都降級，不中斷）
        if len(positive) < request.max_sources:
            try:
                live = await self._twcampus.discover(request)
                seen_urls = {s.official_url for s in positive}
                for s in live:
                    if s.official_url not in seen_urls and len(positive) < request.max_sources:
                        positive.append(s)
                        seen_urls.add(s.official_url)
            except Exception as exc:  # noqa: BLE001
                log.info("TWCampus supplement skipped: %s", exc)

        # Fallback：若仍無正分平台，退回所有有效（≥0分）的本地平台
        if not positive:
            positive = [s for _, s in ranked]

        top = positive[: request.max_sources]
        return [_source_to_dict(s) for s in top]

    # ── browse_education_source ───────────────────────────────────────────────

    async def browse_source(self, request: BrowseRequest) -> dict[str, Any]:
        source = (
            self._router.find_by_name(request.source_name_or_url)
            or self._router.find_by_url(request.source_name_or_url)
        )
        if source is None:
            # 使用者直接傳入 URL 或未知平台名稱 → 建立臨時 source
            raw = request.source_name_or_url
            url = raw if raw.startswith("http") else f"https://{raw}"
            source = EducationSource(
                name=raw,
                official_url=url,
                description="",
                access_strategy=AccessStrategy.WEB_SEARCH,
            )

        results = await self._web.browse(source, request)
        return {
            "source": source.name,
            "official_url": source.official_url,
            "query": request.query,
            "total_returned": len(results),
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "summary": r.summary,
                    "source_name": r.source_name,
                    "source_url": r.source_url,
                    "education_stage": r.education_stage,
                    "subject": r.subject,
                }
                for r in results
            ],
        }

    # ── read_education_resource ───────────────────────────────────────────────

    async def read_resource(self, request: ReadRequest) -> dict[str, Any]:
        return await self._web.read(request.url, list(request.extract))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _source_to_dict(s: EducationSource) -> dict[str, Any]:
    return {
        "name": s.name,
        "reason": s.description,
        "official_url": s.official_url,
        "education_stages": list(s.education_stages),
        "categories": list(s.categories),
        "directory_source": s.directory_source,
        "access_strategy": s.access_strategy.value,
    }
