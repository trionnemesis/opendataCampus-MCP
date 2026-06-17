"""CeecExamAdapter — CEEC 大考中心歷屆試題（學測 / 分科測驗）。

以官方 listing 頁（server-rendered `<table>`）取得考古題的 PDF 下載連結與 metadata,
回傳結構化 ExamQuestionResult。護欄：只解析 listing、回傳連結字串,
**完全不 fetch / 不儲存 PDF 全文**;分頁受 BrowserPolicy（≤2 頁/請求、3 req/min）約束。

listing：`GET /xmfile?xsmsid={XSMSID}&page={N}`
  每列 `<tr>` 3 欄：公告日期 / 列標題（NNN學年度XXX－科目）/ 多個試題-答案 PDF 連結。
  td[2] 內每個 `<a href="/files/file_pool/...">` 攤平成一筆 ExamQuestionResult。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from opendata_campus_mcp.adapters._http import build_ssl_context
from opendata_campus_mcp.contracts import (
    ExamQuestionResult,
    ExamSearchRequest,
    LoginRequiredError,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy

log = logging.getLogger(__name__)

_BASE = "https://www.ceec.edu.tw"
_DOMAIN = "www.ceec.edu.tw"
_USER_AGENT = "Education-Resource-Browser-MCP/1.0 (non-commercial; user-triggered)"
_TIMEOUT = 20.0

# exam_type → listing xsmsid（學測 / 分科一般試題）。
# 會考因 robots.txt Disallow 不納入；CEEC 特殊試題（身障考生用）另有 xsmsid,暫不納入。
_XSMSID: dict[str, str] = {
    "學測": "0J052424829869345634",
    "分科測驗": "0J052427633128416650",
}

_YEAR_RE = re.compile(r"^(\d{2,3})學年度")
_PAREN_RE = re.compile(r"[（(].*?[）)]")
_DASHES = ("－", "—", "-")


class CeecExamAdapter:
    """CEEC 考古題 adapter（實作 ExamArchiveAdapter Protocol）。"""

    def __init__(self, policy: BrowserPolicy) -> None:
        self._policy = policy
        self._client = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
            verify=build_ssl_context(),  # CEEC 是 .edu.tw 政府站
        )

    async def search(self, request: ExamSearchRequest) -> list[ExamQuestionResult]:
        xsmsid = _XSMSID.get(request.exam_type)
        if xsmsid is None:
            # 不支援的 exam_type（會考等）→ 回空,由 server 白名單先擋,此為防呆
            return []

        results: list[ExamQuestionResult] = []
        seen: set[str] = set()
        page = 1
        pages_used = 0

        # 受控分頁：掃滿 max_pages_per_request 即優雅停止（非遞迴、非排程）。
        while len(results) < request.max_results and pages_used < self._policy.max_pages_per_request:
            self._policy.check_page_limit(pages_used)  # 一致性斷言（迴圈條件已保證不超限）
            self._policy.check_rate_limit(_DOMAIN)      # 跨請求速率保護（超限 raise）

            url = f"{_BASE}/xmfile?xsmsid={xsmsid}&page={page}"
            html = await self._fetch(url)
            pages_used += 1

            page_results = self._parse_listing(html, request.exam_type, url)
            if not page_results:
                break  # 超出總頁數

            for r in page_results:
                if r.download_url in seen or not self._matches(r, request):
                    continue
                seen.add(r.download_url)
                results.append(r)
                if len(results) >= request.max_results:
                    break
            page += 1

        return results

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _fetch(self, url: str) -> str:
        log.debug("ceec_exam: GET %s", url)
        try:
            resp = await self._client.get(url)
        except httpx.TransportError as exc:
            raise SourceUnavailableError("CEEC 大考中心", url, str(exc))
        if resp.status_code in (401, 403):
            raise LoginRequiredError(f"login required for CEEC ({url})")
        if resp.status_code >= 400:
            raise SourceUnavailableError("CEEC 大考中心", url, f"HTTP {resp.status_code}")
        return resp.text

    def _parse_listing(
        self, html: str, exam_type: str, listing_url: str
    ) -> list[ExamQuestionResult]:
        soup = BeautifulSoup(html, "html.parser")
        source = f"CEEC 大考中心 | {listing_url}"
        results: list[ExamQuestionResult] = []

        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            pdf_links = [
                a for a in tds[2].find_all("a", href=True)
                if "/files/file_pool/" in a["href"]
            ]
            if not pdf_links:
                continue

            published = tds[0].get_text(strip=True) or None
            year, subject = self._parse_year_subject(tds[1].get_text(" ", strip=True))

            for a in pdf_links:
                label = a.get_text(strip=True)
                file_title = (a.get("title") or label).strip()
                results.append(
                    ExamQuestionResult(
                        exam_type=exam_type,
                        year=year,
                        subject=subject,
                        paper_type=self._classify_paper_type(label, file_title),
                        title=file_title,
                        download_url=urljoin(_BASE, a["href"]),
                        source=source,
                        published=published,
                    )
                )
        return results

    @staticmethod
    def _matches(r: ExamQuestionResult, request: ExamSearchRequest) -> bool:
        if request.year and r.year != request.year:
            return False
        if request.subject and request.subject not in r.subject:
            return False
        return True

    @staticmethod
    def _parse_year_subject(title: str) -> tuple[str, str]:
        """從列標題（如「115學年度學科能力測驗－國綜」）解析民國年與科目。

        解析失敗時 year="" 且 subject=原標題（保留資訊,不丟筆）。
        """
        m = _YEAR_RE.match(title)
        year = m.group(1) if m else ""
        subject = title
        for dash in _DASHES:
            if dash in title:
                subject = title.rsplit(dash, 1)[-1].strip()
                break
        subject = _PAREN_RE.sub("", subject).strip()
        return year, subject

    @staticmethod
    def _classify_paper_type(label: str, file_title: str) -> str:
        text = f"{label} {file_title}"
        if any(k in text for k in ("答案", "評分原則", "參考答案")):
            return "答案"
        if any(k in text for k in ("試題", "試卷")):
            return "試題"
        return "其他"  # 答題卷等

    async def aclose(self) -> None:
        await self._client.aclose()
