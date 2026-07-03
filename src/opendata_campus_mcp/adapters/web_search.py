"""WebSearchAdapter — 官方教育平台 HTTP 搜尋 + 單頁讀取。

策略：
  1. 查 SEARCH_TEMPLATES 取已知搜尋 URL 樣板
  2. 未知平台以 ?q= / ?keyword= / ?search= 通用 fallback
  3. 結果解析：article > .result > .item > li（依序嘗試）
  4. 摘要優先取 <meta name="description">，否則取前 3 段文字
  5. 401/403 → LoginRequiredError；其他網路錯誤 → SourceUnavailableError
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from opendata_campus_mcp.adapters._http import build_ssl_context
from opendata_campus_mcp.adapters.safe_http import safe_get
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    EducationSource,
    LoginRequiredError,
    SearchResult,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.repository.source_cache import get_known_sources

log = logging.getLogger(__name__)

_USER_AGENT = "Education-Resource-Browser-MCP/1.0 (non-commercial; user-triggered)"
_MAX_SUMMARY_CHARS = 500

# 已知平台搜尋 URL 樣板（{query} 會被 URL encode 後替換）
# 教育雲（cloud.edu.tw）搜尋為前端 JS 驅動、無 server 端 GET 搜尋頁，故以首頁為資源入口（伺服器端忽略關鍵字）
SEARCH_TEMPLATES: dict[str, str] = {
    "教育大市集": "https://market.cloud.edu.tw/index.php?inter=search&keyword={query}",
    "因材網": "https://adl.edu.tw/?s={query}",
    "CIRN": "https://cirn.moe.edu.tw/Module/Basic/bsSearch.aspx?search={query}",
    "教育部數位教學資源入口網": "https://cloud.edu.tw/?q={query}",
    "國教院課程資源網": "https://www.naer.edu.tw/PageSearch?q={query}",
}


class WebSearchAdapter:
    access_strategy = AccessStrategy.WEB_SEARCH

    def __init__(
        self,
        policy: BrowserPolicy | None = None,
        url_policy: PublicEducationUrlPolicy | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._policy = policy or BrowserPolicy()
        self._url_policy = url_policy or PublicEducationUrlPolicy.from_sources(
            get_known_sources().values()
        )
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=20.0,
            follow_redirects=False,
            verify=build_ssl_context(),
        )

    async def browse(
        self, source: EducationSource, request: BrowseRequest
    ) -> list[SearchResult]:
        search_url = self._build_search_url(source, request.query)
        log.debug("browse: GET %s", search_url)

        try:
            resp = await safe_get(
                self._client,
                search_url,
                url_policy=self._url_policy,
                browser_policy=self._policy,
            )
        except httpx.TransportError as exc:
            raise SourceUnavailableError(source.name, source.official_url, str(exc))

        if resp.status_code in (401, 403):
            raise LoginRequiredError(
                f"login required for {source.name} ({source.official_url})"
            )
        if resp.status_code >= 400:
            raise SourceUnavailableError(
                source.name, source.official_url, f"HTTP {resp.status_code}"
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_results(soup, source, request.max_results)

    async def read(self, url: str, extract: list[str]) -> dict[str, Any]:
        log.debug("read: GET %s", url)
        try:
            resp = await safe_get(
                self._client,
                url,
                url_policy=self._url_policy,
                browser_policy=self._policy,
            )
        except httpx.TransportError as exc:
            raise SourceUnavailableError("unknown", url, str(exc))

        if resp.status_code in (401, 403):
            raise LoginRequiredError(f"login required for {url}")
        if resp.status_code >= 400:
            raise SourceUnavailableError("unknown", url, f"HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")
        return self._extract_fields(soup, url, extract)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _build_search_url(self, source: EducationSource, query: str) -> str:
        template = SEARCH_TEMPLATES.get(source.name)
        if template:
            return template.format(query=quote(query, safe=""))

        # 通用 fallback：嘗試 ?q= 附加至官方 URL
        base = source.official_url.rstrip("/")
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}q={quote(query, safe='')}"

    def _parse_results(
        self,
        soup: BeautifulSoup,
        source: EducationSource,
        max_results: int,
    ) -> list[SearchResult]:
        # 通用路徑：依序嘗試常見結果容器
        items: list[Tag] = (
            soup.find_all("article")  # type: ignore[assignment]
            or soup.find_all(class_=lambda c: c and "result" in c.lower())
            or soup.find_all(class_=lambda c: c and "item" in c.lower())
            or soup.find_all("li")
        )

        results: list[SearchResult] = []
        for item in items:
            link = item.find("a", href=True)
            if not link:
                continue
            href: str = link["href"]
            if not href.startswith("http"):
                href = urljoin(source.official_url, href)

            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # 取相鄰摘要文字
            summary_el = item.find(["p", "div", "span"])
            raw_summary = summary_el.get_text(strip=True) if summary_el else ""
            summary = raw_summary[:_MAX_SUMMARY_CHARS]

            results.append(
                SearchResult(
                    title=title,
                    url=href,
                    summary=summary,
                    source_name=source.name,
                    source_url=source.official_url,
                )
            )
            if len(results) >= max_results:
                break

        return results

    def _extract_fields(
        self,
        soup: BeautifulSoup,
        url: str,
        extract: list[str],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"url": url}

        if "title" in extract:
            title_el = soup.find("title") or soup.find("h1")
            result["title"] = title_el.get_text(strip=True) if title_el else ""

        if "summary" in extract:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            meta_content = str(meta_desc["content"]).strip() if meta_desc and meta_desc.get("content") else ""  # type: ignore[index]
            # 若 meta description 有實質內容（>30 字元且非僅網站名稱），優先使用
            if len(meta_content) > 30:
                result["summary"] = meta_content[:_MAX_SUMMARY_CHARS]
            else:
                # Fallback：取頁面 body 有意義的文字段落
                main = soup.find("main") or soup.find("article") or soup.find("body")
                texts: list[str] = []
                seen_body: set[str] = set()
                for el in (main.find_all(["p", "li", "span", "div"]) if main else []):
                    t = el.get_text(strip=True)
                    if t and len(t) > 10 and t not in seen_body:
                        seen_body.add(t)
                        texts.append(t)
                    if len(texts) >= 4:
                        break
                result["summary"] = " ".join(texts)[:_MAX_SUMMARY_CHARS]

        if "publisher" in extract:
            result["publisher"] = _meta(
                soup, "DC.Publisher", "og:site_name", "author", "publisher", "creator", "DC.Creator"
            )

        if "education_stage" in extract:
            # 實測現有來源皆無可靠 educationLevel meta；保留防禦性查詢，命不到即 None（不臆造）
            result["education_stage"] = _meta(soup, "dc.educationLevel", "dcterms.educationLevel")

        if "subject" in extract:
            # 僅取 Dublin Core subject；不把 SEO keywords 當學科（實測 keywords≠subject）
            result["subject"] = _meta(soup, "DC.Subject", "dc.subject", "dcterms.subject")

        if "license" in extract:
            lic = _meta(soup, "DC.Rights", "dc.rights", "license", "rights", "copyright")
            if not lic:
                for link in soup.find_all("link", href=True):
                    rel = link.get("rel")
                    rel_str = " ".join(rel) if isinstance(rel, list) else str(rel or "")
                    if "license" in rel_str.lower():
                        lic = str(link["href"])
                        break
            result["license"] = lic

        return result

    async def aclose(self) -> None:
        await self._client.aclose()


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    """case-insensitive 取第一個命中的 <meta name|property> content；空值/無 → None。

    跨來源 meta 萃取共用：統一 lower-case 比對（解決 BS4 屬性值大小寫敏感）、
    空字串視為未命中（NLPI 等的 DC.* 常為空），不臆造。
    """
    wanted = {n.lower() for n in names}
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").lower()
        if key in wanted:
            content = (tag.get("content") or "").strip()
            if content:
                return content
    return None
