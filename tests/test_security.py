"""安全回歸測試 — 鎖住已修正漏洞的觸發條件。

每個 class 對應一項已確認的問題;測試同時涵蓋「攻擊被擋下」與
「正常輸入行為不變」兩面,避免修正造成功能退化。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from opendata_campus_mcp.adapters.ceec_exam import CeecExamAdapter, _ceec_download_url
from opendata_campus_mcp.adapters.web_search import WebSearchAdapter
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    DiscoveryRequest,
    EducationSource,
    ExamSearchRequest,
    PolicyViolationError,
    ReadRequest,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.domain.url_policy import (
    PublicEducationUrlPolicy,
    safe_result_url,
)
from opendata_campus_mcp.mcp_server.service import EdBrowserService
from opendata_campus_mcp.repository.source_cache import get_known_sources

_SOURCE = EducationSource(
    name="教育大市集",
    official_url="https://market.cloud.edu.tw",
    access_strategy=AccessStrategy.WEB_SEARCH,
)


# ── 1. 回傳連結的 scheme 白名單(CWE-79 / CWE-601)──────────────────────────


class TestSafeResultUrl:
    """urljoin 對未知 scheme 是原樣回傳,必須另外過濾才擋得住。"""

    @pytest.mark.parametrize(
        "href",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",  # 大小寫混淆
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "",
        ],
    )
    def test_dangerous_scheme_rejected(self, href: str) -> None:
        assert safe_result_url(href, "https://market.cloud.edu.tw/a") is None

    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            ("/res/1", "https://market.cloud.edu.tw/res/1"),
            ("res/1", "https://market.cloud.edu.tw/a/res/1"),
            ("https://adl.edu.tw/x", "https://adl.edu.tw/x"),
            ("//adl.edu.tw/x", "https://adl.edu.tw/x"),
        ],
    )
    def test_legitimate_href_resolved(self, href: str, expected: str) -> None:
        assert safe_result_url(href, "https://market.cloud.edu.tw/a/") == expected


class TestWebSearchResultScheme:
    """搜尋結果的 href 來自遠端 HTML,不可原樣交給 client。"""

    def _parse(self, html: str) -> list:
        adapter = WebSearchAdapter()
        return adapter._parse_results(
            BeautifulSoup(html, "html.parser"), _SOURCE, max_results=10
        )

    def test_javascript_href_dropped(self) -> None:
        html = (
            "<article><a href=\"javascript:alert(1)\">惡意連結標題</a></article>"
            "<article><a href=\"/ok\">正常資源標題</a></article>"
        )
        results = self._parse(html)
        assert [r.url for r in results] == ["https://market.cloud.edu.tw/ok"]

    def test_relative_href_still_resolved(self) -> None:
        """既有行為:相對路徑仍要正確解析為絕對 URL。"""
        results = self._parse('<article><a href="/res/1">教材標題</a></article>')
        assert results[0].url == "https://market.cloud.edu.tw/res/1"


class TestCeecDownloadUrlHost:
    """`/files/file_pool/` 是子字串比對,絕對 href 同樣會通過該過濾。"""

    def test_offsite_pdf_href_rejected(self) -> None:
        assert (
            _ceec_download_url("https://evil.example/files/file_pool/x.pdf") is None
        )

    def test_onsite_pdf_href_accepted(self) -> None:
        assert (
            _ceec_download_url("/files/file_pool/x.pdf")
            == "https://www.ceec.edu.tw/files/file_pool/x.pdf"
        )

    def test_listing_drops_offsite_row_keeps_onsite(self) -> None:
        html = (
            "<table><tr>"
            "<td>115-02-23</td><td>115學年度學科能力測驗－國綜</td>"
            '<td><a href="https://evil.example/files/file_pool/bad.pdf">試題</a>'
            '<a href="/files/file_pool/good.pdf">試題</a></td>'
            "</tr></table>"
        )
        adapter = CeecExamAdapter(BrowserPolicy())
        rows = adapter._parse_listing(html, "學測", "https://www.ceec.edu.tw/xmfile")
        assert [r.download_url for r in rows] == [
            "https://www.ceec.edu.tw/files/file_pool/good.pdf"
        ]


# ── 2. HeadlessAdapter 的 URL 護欄(CWE-918 / CWE-20)────────────────────────


class TestHeadlessUrlGuards:
    """此 adapter 先前完全繞過目錄白名單,且 query 未編碼。"""

    @pytest.fixture
    def adapter(self):
        from opendata_campus_mcp.adapters.headless import HeadlessAdapter

        with pytest.warns(UserWarning):
            return HeadlessAdapter(enabled=True)

    def test_source_outside_catalog_rejected(self, adapter) -> None:
        """_build_search_url 在 playwright 啟動前執行,故不需真的開瀏覽器。"""
        evil = EducationSource(
            name="evil",
            official_url="https://evil.example",
            access_strategy=AccessStrategy.HEADLESS_BROWSER,
        )
        with pytest.raises(PolicyViolationError):
            adapter._build_search_url(evil, "x")

    def test_query_is_url_encoded(self, adapter) -> None:
        """未編碼時 query 內的 & 會新增參數、# 會截斷 URL。"""
        url = adapter._build_search_url(_SOURCE, "數學&admin=1#frag")
        assert url == (
            "https://market.cloud.edu.tw"
            "?q=%E6%95%B8%E5%AD%B8%26admin%3D1%23frag"
        )

    def test_catalog_source_accepted(self, adapter) -> None:
        """既有行為:目錄內的來源仍可正常組出搜尋 URL。"""
        assert adapter._build_search_url(_SOURCE, "數學").startswith(
            "https://market.cloud.edu.tw?q="
        )


# ── 3. 工具參數長度上限(CWE-20 / CWE-400)───────────────────────────────────


def _service() -> EdBrowserService:
    known = get_known_sources()
    policy = BrowserPolicy()
    router = SourceRouter(known)
    url_policy = PublicEducationUrlPolicy.from_sources(known.values())

    class _Unused:
        async def browse(self, *_a, **_k):  # pragma: no cover - 不應被呼叫
            raise AssertionError("長度檢查必須在觸及 adapter 前就擋下")

        async def discover(self, *_a, **_k):  # pragma: no cover
            raise AssertionError("長度檢查必須在觸及 adapter 前就擋下")

        async def search(self, *_a, **_k):  # pragma: no cover
            raise AssertionError("長度檢查必須在觸及 adapter 前就擋下")

    unused = _Unused()
    return EdBrowserService(
        policy, router, unused, {}, fallback=unused,
        exam_adapter=unused, url_policy=url_policy,
    )


class TestInputLengthLimits:
    async def test_discover_query_too_long_rejected(self) -> None:
        with pytest.raises(PolicyViolationError, match="query too long"):
            await _service().discover_sources(DiscoveryRequest(query="x" * 201))

    async def test_browse_query_too_long_rejected(self) -> None:
        with pytest.raises(PolicyViolationError, match="query too long"):
            await _service().browse_source(
                BrowseRequest(source_name_or_url="教育大市集", query="x" * 201)
            )

    async def test_read_url_too_long_rejected(self) -> None:
        with pytest.raises(PolicyViolationError, match="url too long"):
            await _service().read_resource(
                ReadRequest(url="https://market.cloud.edu.tw/" + "x" * 2048)
            )

    async def test_exam_subject_too_long_rejected(self) -> None:
        with pytest.raises(PolicyViolationError, match="subject too long"):
            await _service().search_exam_questions(
                ExamSearchRequest(exam_type="學測", subject="x" * 201)
            )

    async def test_query_at_limit_still_works(self) -> None:
        """上限之內的輸入不得被誤擋(避免修正造成功能退化)。"""
        result = await _service().discover_sources(
            DiscoveryRequest(query="x" * 200, max_sources=1)
        )
        assert isinstance(result, list)


# ── 4. 相依套件版本下限(CWE-1035)──────────────────────────────────────────


class TestFastMcpDependencyFloor:
    """fastmcp < 3.2.0 有已知通報(PYSEC-2026-2475 / 2476 等)。"""

    def test_declared_floor_excludes_vulnerable_versions(self) -> None:
        from packaging.requirements import Requirement
        from packaging.version import Version

        text = Path("pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'"(fastmcp[^"]*)"', text)
        assert m, "pyproject.toml 找不到 fastmcp 相依宣告"
        req = Requirement(m.group(1))
        for vulnerable in ("0.2.0", "2.0.0", "3.1.0"):
            assert not req.specifier.contains(Version(vulnerable)), (
                f"fastmcp 版本下限仍允許有已知漏洞的 {vulnerable}"
            )
        assert req.specifier.contains(Version("3.2.0"))

    def test_installed_version_meets_floor(self) -> None:
        from importlib.metadata import version

        from packaging.version import Version

        assert Version(version("fastmcp")) >= Version("3.2.0")
