"""EduMarketApiAdapter — 教育大市集官方 v2 REST API（OFFICIAL_API 策略）。

以官方 API 取代猜測式 HTML 解析,回傳對齊網站提供的結構化資料：
  GET /api/v2/search/edumarket/{keyword}?key=&page=&rows=
  → JSON 信封 {status, msg, page, totalpage, resources:[...]}
  → 每筆 Resources 含 edugrade(學制)/domain(領域)/copyright(授權) 等結構化欄位

key 由環境變數 EDUMARKET_API_KEY 注入；無 key 時 browse 回傳明確 unavailable，
不降級至已知會失敗的 WebSearchAdapter 路徑。
read 無 by-id 詳情端點,委派給注入的 html_reader（通常為 WebSearchAdapter）。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

from opendata_campus_mcp.adapters._http import build_ssl_context
from opendata_campus_mcp.adapters.safe_http import bounded_get
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseAdapter,
    BrowseRequest,
    EducationSource,
    LoginRequiredError,
    SearchResult,
    SourceUnavailableError,
)

log = logging.getLogger(__name__)

_BASE = "https://market.cloud.edu.tw/api"
_USER_AGENT = "Education-Resource-Browser-MCP/1.0 (non-commercial; user-triggered)"
_MAX_SUMMARY_CHARS = 500
_TIMEOUT = 20.0


class EduMarketApiAdapter:
    """教育大市集官方 API adapter（實作 BrowseAdapter Protocol）。"""

    access_strategy = AccessStrategy.OFFICIAL_API

    def __init__(
        self,
        api_key: str | None = None,
        html_reader: BrowseAdapter | None = None,
    ) -> None:
        # key 可顯式傳入（測試用）或回退環境變數
        self._api_key = api_key or os.environ.get("EDUMARKET_API_KEY")
        # read 無 by-id 詳情端點,委派給 HTML reader
        self._html_reader = html_reader
        self._client = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
            verify=build_ssl_context(),
        )

    async def browse(
        self, source: EducationSource, request: BrowseRequest
    ) -> list[SearchResult]:
        if not self._api_key:
            # 無 key 是可預期設定狀態；必須在建立 HTTP request 前停止。
            raise SourceUnavailableError(
                source.name, source.official_url, "EDUMARKET_API_KEY not configured"
            )

        # keyword 是 path 參數（中文需 encode）；key/page/rows 為 query
        kw = quote(request.query, safe="")
        url = (
            f"{_BASE}/v2/search/edumarket/{kw}"
            f"?key={self._api_key}&page=1&rows={request.max_results}"
        )
        log.debug("edumarket browse: GET /v2/search/edumarket/%s", kw)

        try:
            # bounded_get:回應大小上限(CWE-400)。固定端點的 JSON API,
            # 上游實際 Content-Type 未經本機驗證,故不加型別白名單。
            resp = await bounded_get(self._client, url, allowed_content_types=None)
        except httpx.TransportError as exc:
            raise SourceUnavailableError(source.name, source.official_url, str(exc))

        if resp.status_code in (401, 403):
            raise LoginRequiredError(
                f"login required / invalid key for {source.name} ({source.official_url})"
            )
        if resp.status_code >= 400:
            raise SourceUnavailableError(
                source.name, source.official_url, f"HTTP {resp.status_code}"
            )

        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError):
            raise SourceUnavailableError(
                source.name, source.official_url, "invalid JSON response"
            )

        # 信封 status：1=成功；0=失敗。無效 key 常以 HTTP 200 + status:0 回應,
        # 故此處是真正的 auth/失敗判斷點（非僅靠 HTTP 4xx）。
        if data.get("status") != 1:
            raise SourceUnavailableError(
                source.name,
                source.official_url,
                f"status={data.get('status')}: {data.get('msg', '')}",
            )

        resources = data.get("resources") or []
        return [
            self._to_search_result(item, source)
            for item in resources[: request.max_results]
        ]

    async def read(self, url: str, extract: list[str]) -> dict[str, Any]:
        # 教育大市集 API 無 by-id 詳情端點 → 委派給 HTML reader
        if self._html_reader is None:
            raise SourceUnavailableError(
                "教育大市集", url, "no html_reader configured for read"
            )
        return await self._html_reader.read(url, extract)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _to_search_result(
        self, item: dict[str, Any], source: EducationSource
    ) -> SearchResult:
        domains = item.get("domain") or []
        subject = "、".join(domains) if domains else None
        # publisher 取首位貢獻者機構；copyright 是「授權」,勿混為 publisher
        contributors = item.get("contributor") or []
        publisher = contributors[0].get("org") if contributors else None
        return SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            summary=(item.get("desc") or "")[:_MAX_SUMMARY_CHARS],
            source_name=source.name,
            source_url=source.official_url,
            education_stage=item.get("edugrade") or None,
            subject=subject,
            publisher=publisher,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
