"""OpenDataApiAdapter — 政府資料開放平臺（data.gov.tw）教育 open data（OPEN_DATA 策略）。

唯一提供結構化、附實際 CSV/JSON 下載點的官方來源,補齊其他 adapter 只回網頁連結的空白。

- browse(source, request)：在預先驗證的 dataset catalog（opendata_catalog）本地關鍵字過濾
  → SearchResult。**不打 API**（無匿名搜尋 API,且 catalog 已備妥,省請求）。
- read(url, extract)：抽 dataset id → GET /api/v2/rest/dataset/{id} → 取 result,
  回 dict 含 license 解碼 + `resources` 陣列（CSV/JSON 下載點）。本來就有結構化 API,
  read 不降級回 html_reader（與 edumarket 不同）。

信封 `{success, result, help}`：失敗 `success=false`+`error`（HTTP 仍 200 → 看 flag,
與 edumarket `status!=1` 同構）。資料皆教育部統計處/高教司,授權 OGDL v1.0。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from opendata_campus_mcp.adapters._http import build_ssl_context
from opendata_campus_mcp.adapters.safe_http import safe_get
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    EducationSource,
    SearchResult,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.repository.opendata_catalog import (
    OpenDataset,
    get_opendata_catalog,
)
from opendata_campus_mcp.repository.source_cache import get_known_sources

log = logging.getLogger(__name__)

_BASE = "https://data.gov.tw"
_USER_AGENT = "Education-Resource-Browser-MCP/1.0 (non-commercial; user-triggered)"
_MAX_SUMMARY_CHARS = 500
_TIMEOUT = 20.0
_DATASET_ID_RE = re.compile(r"dataset/(\d+)")


class OpenDataApiAdapter:
    """data.gov.tw 教育 open data adapter（實作 BrowseAdapter Protocol）。"""

    access_strategy = AccessStrategy.OPEN_DATA

    def __init__(self) -> None:
        # 固定端點仍需逐跳驗證 redirect:上游 open redirect 或站台被入侵時,
        # follow_redirects=True 會把請求帶往 localhost / 雲端 metadata(CWE-918)。
        # 沿用與 WebSearchAdapter 相同的 catalog 白名單作為信任邊界。
        self._url_policy = PublicEducationUrlPolicy.from_sources(
            get_known_sources().values()
        )
        self._client = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=False,
            verify=build_ssl_context(),
        )

    async def browse(
        self, source: EducationSource, request: BrowseRequest
    ) -> list[SearchResult]:
        # 純 catalog 本地關鍵字過濾,不打 API
        tokens = {t for t in request.query.lower().split() if t}
        scored: list[tuple[int, OpenDataset]] = []
        for ds in get_opendata_catalog():
            haystack = " ".join([ds.title, ds.summary, *ds.keywords, *ds.education_stages]).lower()
            scored.append((sum(1 for t in tokens if t in haystack), ds))
        scored.sort(key=lambda x: -x[0])

        limit = min(request.max_results, 5)
        positive = [ds for sc, ds in scored if sc > 0]
        # 無關鍵字命中 → 退回目錄前 N（仍給使用者可用結果）
        chosen = (positive or [ds for _, ds in scored])[:limit]
        return [self._to_search_result(ds, source) for ds in chosen]

    async def read(self, url: str, extract: list[str]) -> dict[str, Any]:
        m = _DATASET_ID_RE.search(url)
        if not m:
            raise SourceUnavailableError(
                "政府資料開放平臺", url, "URL 不含 data.gov.tw dataset id"
            )
        api_url = f"{_BASE}/api/v2/rest/dataset/{m.group(1)}"
        log.debug("opendata read: GET %s", api_url)

        try:
            resp = await safe_get(
                self._client, api_url, url_policy=self._url_policy
            )
        except httpx.TransportError as exc:
            raise SourceUnavailableError("政府資料開放平臺", url, str(exc))
        if resp.status_code >= 400:
            raise SourceUnavailableError(
                "政府資料開放平臺", url, f"HTTP {resp.status_code}"
            )
        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError):
            raise SourceUnavailableError("政府資料開放平臺", url, "invalid JSON response")

        # 失敗以 success flag 判斷（HTTP 仍 200）
        if data.get("success") is not True:
            err = (data.get("error") or {}).get("error_type", "unknown")
            raise SourceUnavailableError(
                "政府資料開放平臺", url, f"dataset 不存在或無法存取（{err}）"
            )

        result = data.get("result") or {}
        ds = _find_in_catalog(m.group(1))
        keywords = result.get("keyword") or []
        distribution = result.get("distribution") or []
        return {
            "url": url,
            "title": result.get("title", ""),
            "summary": (result.get("description") or "")[:_MAX_SUMMARY_CHARS],
            "publisher": "教育部統計處",
            "education_stage": "、".join(ds.education_stages) if ds and ds.education_stages else None,
            "subject": "、".join(keywords) if keywords else None,
            "license": _decode_license(result.get("license")),
            "resources": [
                {"format": d.get("resourceFormat"), "download_url": d.get("resourceDownloadUrl")}
                for d in distribution
                if d.get("resourceDownloadUrl")
            ],
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    def _to_search_result(
        self, ds: OpenDataset, source: EducationSource
    ) -> SearchResult:
        return SearchResult(
            title=ds.title,
            url=f"{_BASE}/dataset/{ds.dataset_id}",
            summary=(ds.summary or ds.title)[:_MAX_SUMMARY_CHARS],
            source_name=source.name,
            source_url=source.official_url,
            education_stage="、".join(ds.education_stages) or None,
            subject="、".join(ds.keywords) or None,
            publisher="教育部統計處",
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _decode_license(value: Any) -> str | None:
    if value == "1":
        return "政府資料開放授權條款-第1版 (OGDL v1.0)"
    return str(value) if value else None


def _find_in_catalog(dataset_id: str) -> OpenDataset | None:
    for ds in get_opendata_catalog():
        if ds.dataset_id == dataset_id:
            return ds
    return None
