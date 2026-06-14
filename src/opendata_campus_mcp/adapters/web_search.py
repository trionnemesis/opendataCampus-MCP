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
import ssl
from typing import Any
from urllib.parse import quote, urljoin

import httpx
import truststore
from bs4 import BeautifulSoup, Tag

from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    EducationSource,
    LoginRequiredError,
    SearchResult,
    SourceUnavailableError,
)

log = logging.getLogger(__name__)

_USER_AGENT = "Education-Resource-Browser-MCP/1.0 (non-commercial; user-triggered)"
_MAX_SUMMARY_CHARS = 500

# 已知平台搜尋 URL 樣板（{query} 會被 URL encode 後替換）
# NTU OCW 的 /courses 路徑被 WAF 封鎖，改以首頁作為課程目錄（首頁含近期課程列表）
# 教育雲（cloud.edu.tw）搜尋為前端 JS 驅動、無 server 端 GET 搜尋頁，故以首頁為資源入口（伺服器端忽略關鍵字）
SEARCH_TEMPLATES: dict[str, str] = {
    "教育大市集": "https://market.cloud.edu.tw/index.php?inter=search&keyword={query}",
    "因材網": "https://adl.edu.tw/?s={query}",
    "CIRN": "https://cirn.moe.edu.tw/Module/Basic/bsSearch.aspx?search={query}",
    "教育部數位教學資源入口網": "https://cloud.edu.tw/?q={query}",
    "國教院課程資源網": "https://www.naer.edu.tw/PageSearch?q={query}",
    "臺大開放式課程 NTU OCW": "https://ocw.aca.ntu.edu.tw/",
}


class WebSearchAdapter:
    access_strategy = AccessStrategy.WEB_SEARCH

    def __init__(self) -> None:
        # 台灣政府教育平台多以 GCA 憑證簽發，部分缺 Subject Key Identifier，
        # 在 certifi + 嚴格 OpenSSL 下會驗證失敗；改用 OS 系統信任庫驗證（不放寬安全）。
        ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._client = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
            verify=ssl_ctx,
        )

    async def browse(
        self, source: EducationSource, request: BrowseRequest
    ) -> list[SearchResult]:
        search_url = self._build_search_url(source, request.query)
        log.debug("browse: GET %s", search_url)

        try:
            resp = await self._client.get(search_url)
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
            resp = await self._client.get(url)
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
        # NTU OCW 首頁特殊路徑：課程以 <a href="/courses/..."> 列出
        if "ocw.aca.ntu.edu.tw" in source.official_url:
            return self._parse_ntu_ocw_homepage(soup, source, max_results)

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

    def _parse_ntu_ocw_homepage(
        self,
        soup: BeautifulSoup,
        source: EducationSource,
        max_results: int,
    ) -> list[SearchResult]:
        """NTU OCW 首頁課程解析：找所有 /courses/<id> 連結，排除純導覽項目。"""
        import re

        results: list[SearchResult] = []
        seen: set[str] = set()
        # 課程連結格式：/courses/<英數id>（非 /courses 本身）
        _course_id_re = re.compile(r"^/courses/\S+$")

        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if not _course_id_re.match(href):
                continue
            full_url = f"https://ocw.aca.ntu.edu.tw{href}"
            if full_url in seen:
                continue
            seen.add(full_url)

            # 取連結所在的最近容器文字作為標題來源
            container = a.find_parent(["li", "div", "article", "section", "span"])
            raw_text = container.get_text(" ", strip=True) if container else a.get_text(strip=True)
            title = a.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            # 從容器文字萃取日期（如 2025/11/22）作為摘要補充
            date_match = re.search(r"\d{4}/\d{2}/\d{2}", raw_text)
            date_str = f"發布日期：{date_match.group()}" if date_match else ""
            summary = f"{date_str} {raw_text.replace(title, '').strip()}"[:_MAX_SUMMARY_CHARS]

            results.append(
                SearchResult(
                    title=title,
                    url=full_url,
                    summary=summary.strip(),
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
            meta = soup.find(
                "meta",
                attrs={"name": lambda n: n in ("author", "publisher", "creator")},
            )
            result["publisher"] = str(meta["content"]) if meta and meta.get("content") else None  # type: ignore[index]

        if "education_stage" in extract:
            result["education_stage"] = None  # 需平台特定解析

        if "subject" in extract:
            result["subject"] = None

        if "license" in extract:
            meta = soup.find(
                "meta",
                attrs={"name": lambda n: n in ("license", "rights", "dc.rights")},
            )
            result["license"] = str(meta["content"]) if meta and meta.get("content") else None  # type: ignore[index]

        return result

    async def aclose(self) -> None:
        await self._client.aclose()
