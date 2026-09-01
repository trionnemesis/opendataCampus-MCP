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
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseAdapter,
    BrowseRequest,
    DiscoveryRequest,
    EducationSource,
    ExamArchiveAdapter,
    ExamQuestionResult,
    ExamSearchRequest,
    PolicyViolationError,
    ReadRequest,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.repository.source_cache import get_known_sources

log = logging.getLogger(__name__)


class EdBrowserService:
    # MCP 工具字串參數的長度上限。這些值會被 URL-encode 進外送 URL、
    # 進到評分迴圈與錯誤訊息;不設限時單一呼叫即可送進 MB 級字串造成
    # 不必要的資源耗用(CWE-20 / CWE-400)。上限遠大於任何真實查詢。
    _MAX_QUERY_LEN = 200
    _MAX_URL_LEN = 2048

    @classmethod
    def _check_len(cls, value: str | None, *, name: str, max_len: int) -> None:
        if value is not None and len(value) > max_len:
            raise PolicyViolationError(
                f"{name} too long ({len(value)} chars, max {max_len})"
            )

    def __init__(
        self,
        policy: BrowserPolicy,
        router: SourceRouter,
        twcampus: TwCampusDirectoryAdapter,
        adapters: dict[AccessStrategy, BrowseAdapter],
        fallback: BrowseAdapter,
        exam_adapter: ExamArchiveAdapter | None = None,
        url_policy: PublicEducationUrlPolicy | None = None,
    ) -> None:
        self._policy = policy
        self._router = router
        self._twcampus = twcampus
        self._adapters = adapters
        self._fallback = fallback
        self._exam_adapter = exam_adapter
        self._url_policy = url_policy or PublicEducationUrlPolicy.from_sources(
            get_known_sources().values()
        )

    # ── discover_education_sources ────────────────────────────────────────────

    async def discover_sources(self, request: DiscoveryRequest) -> list[dict[str, Any]]:
        self._check_len(request.query, name="query", max_len=self._MAX_QUERY_LEN)
        self._check_len(
            request.education_stage, name="education_stage", max_len=self._MAX_QUERY_LEN
        )
        self._check_len(request.subject, name="subject", max_len=self._MAX_QUERY_LEN)
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
        self._check_len(request.query, name="query", max_len=self._MAX_QUERY_LEN)
        self._check_len(
            request.source_name_or_url, name="source", max_len=self._MAX_URL_LEN
        )
        source = (
            self._router.find_by_name(request.source_name_or_url)
            or self._router.find_by_url(request.source_name_or_url)
        )
        if source is None:
            raise PolicyViolationError("browse source is not in the source catalog")

        adapter = self._adapters.get(source.access_strategy, self._fallback)
        results = await adapter.browse(source, request)
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
        # 依資源頁 URL host 找來源 → 取對應 adapter（OPEN_DATA dataset 頁走 OpenData
        # adapter 的結構化 read；其餘 / 未知 host 落 fallback 的 HTML 擷取）。
        self._check_len(request.url, name="url", max_len=self._MAX_URL_LEN)
        self._url_policy.validate(request.url)
        source = self._router.find_by_host(request.url)
        if source is None:
            raise PolicyViolationError("read URL host is not in the source catalog")
        adapter = self._adapters.get(source.access_strategy, self._fallback)
        return await adapter.read(request.url, list(request.extract))

    # ── search_exam_questions ─────────────────────────────────────────────────

    async def search_exam_questions(self, request: ExamSearchRequest) -> dict[str, Any]:
        self._check_len(request.year, name="year", max_len=self._MAX_QUERY_LEN)
        self._check_len(request.subject, name="subject", max_len=self._MAX_QUERY_LEN)
        if self._exam_adapter is None:
            raise SourceUnavailableError(
                "CEEC 大考中心", "https://www.ceec.edu.tw",
                "exam adapter not configured",
            )
        results = await self._exam_adapter.search(request)
        return {
            "exam_type": request.exam_type,
            "year": request.year,
            "subject": request.subject,
            "total_returned": len(results),
            "questions": [_exam_to_dict(r) for r in results],
        }


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


def _exam_to_dict(r: ExamQuestionResult) -> dict[str, Any]:
    return {
        "exam_type": r.exam_type,
        "year": r.year,
        "subject": r.subject,
        "paper_type": r.paper_type,
        "title": r.title,
        "download_url": r.download_url,
        "source": r.source,
        "published": r.published,
    }
