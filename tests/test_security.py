"""Security regression tests — 對應本次資安檢測修正的項目。

涵蓋:
  §1 相依套件版本下限(SCA)
  §2 MCP 工具參數長度/範圍護欄(CWE-20 / CWE-1284)
  §3 出站 URL 政策(CWE-918)—— 既有防護的回歸鎖定
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.mcp_server.validation import (
    InputValidationError,
    check_len,
    clamp_count,
)

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


# ── 1. Dependency floors (SCA) ───────────────────────────────────────────────


class TestDependencyFloors:
    """宣告的版本下限不可放行已知有漏洞的版本。

    fastmcp < 3.2.0 命中 PYSEC-2026-2475 / PYSEC-2026-2476(另有
    PYSEC-2026-1364/1365、PYSEC-2026-2474、GHSA-rcfx-77hg-w2wv 在更早版本修掉)。
    先前宣告的是 `fastmcp>=0.2.0`,實際解析雖會拿到新版,但在有其他約束的環境
    仍可能裝到有漏洞的版本。
    """

    @staticmethod
    def _spec(name: str) -> str:
        text = PYPROJECT.read_text(encoding="utf-8")
        m = re.search(rf'"({re.escape(name)}[^"]*)"', text)
        assert m, f"{name} dependency spec not found in pyproject.toml"
        return m.group(1)

    def test_fastmcp_floor_excludes_vulnerable_versions(self) -> None:
        from packaging.requirements import Requirement
        from packaging.version import Version

        req = Requirement(self._spec("fastmcp"))
        assert not req.specifier.contains(Version("3.1.0")), (
            "fastmcp floor permits versions affected by "
            "PYSEC-2026-2475 / PYSEC-2026-2476 (fixed in 3.2.0)"
        )
        assert req.specifier.contains(Version("3.2.0"))

    def test_installed_fastmcp_meets_floor(self) -> None:
        from importlib.metadata import version

        from packaging.version import Version

        assert Version(version("fastmcp")) >= Version("3.2.0")

    def test_pytest_floor_excludes_vulnerable_versions(self) -> None:
        from packaging.requirements import Requirement
        from packaging.version import Version

        req = Requirement(self._spec("pytest"))
        assert not req.specifier.contains(Version("9.0.2")), (
            "pytest floor permits versions affected by PYSEC-2026-1845 "
            "(fixed in 9.0.3)"
        )


# ── 2. Tool input bounds (CWE-20 / CWE-1284) ─────────────────────────────────


class TestInputBounds:
    """先前工具參數完全無長度上限。

    唯一的實際邊界是 httpx 的 65536-byte URL 上限,超過時丟的
    `httpx.InvalidURL` 並非 `httpx.TransportError`,adapter 的
    `except httpx.TransportError` 接不到,例外會直接穿出工具。
    """

    def test_check_len_rejects_oversized(self) -> None:
        with pytest.raises(InputValidationError, match="query too long"):
            check_len("x" * 501, name="query", max_len=500)

    def test_check_len_accepts_at_limit(self) -> None:
        check_len("x" * 500, name="query", max_len=500)

    def test_check_len_ignores_none(self) -> None:
        check_len(None, name="subject", max_len=100)

    def test_httpx_invalid_url_is_not_a_transport_error(self) -> None:
        """記錄住促成本護欄的前提:adapter 的 except 子句接不到它。"""
        import httpx

        assert not issubclass(httpx.InvalidURL, httpx.TransportError)

    @pytest.mark.parametrize(
        ("value", "expected"), [(-1, 1), (0, 1), (1, 1), (3, 3), (5, 5), (999, 5)]
    )
    def test_clamp_count_bounds_both_ends(self, value: int, expected: int) -> None:
        assert clamp_count(value, max_value=5) == expected


class TestToolsRejectOversizedInput:
    """工具層真的有接上護欄,且回的是既有的 error-dict 形狀(不是拋例外)。"""

    @staticmethod
    async def _call(name: str, arguments: dict):
        from opendata_campus_mcp.mcp_server import server as server_module

        mcp = server_module.build_server()
        async with mcp._lifespan_manager():
            return await mcp.call_tool(name, arguments)

    async def test_browse_rejects_oversized_query(self) -> None:
        result = await self._call(
            "browse_education_source",
            {"source": "教育大市集", "query": "x" * 5000},
        )
        assert result.structured_content["error"] == "invalid_input"
        assert "query too long" in result.structured_content["message"]

    async def test_read_rejects_oversized_url(self) -> None:
        result = await self._call(
            "read_education_resource",
            {"url": "https://market.cloud.edu.tw/" + "x" * 5000},
        )
        assert result.structured_content["error"] == "invalid_input"
        assert "url too long" in result.structured_content["message"]

    async def test_discover_rejects_oversized_query(self) -> None:
        result = await self._call(
            "discover_education_sources", {"query": "x" * 5000}
        )
        assert "query too long" in str(result.structured_content)

    async def test_exam_search_rejects_oversized_subject(self) -> None:
        result = await self._call(
            "search_exam_questions", {"exam_type": "學測", "subject": "x" * 5000}
        )
        assert result.structured_content["error"] == "invalid_input"
        assert "subject too long" in result.structured_content["message"]

    async def test_normal_query_is_not_rejected(self) -> None:
        """護欄不得誤殺正常查詢 —— 這條失敗代表上限訂太緊。"""
        result = await self._call(
            "discover_education_sources", {"query": "高中 數學 教材"}
        )
        assert "invalid_input" not in str(result.structured_content)


# ── 3. Outbound URL policy (CWE-918) — 既有防護的回歸鎖定 ────────────────────


class TestOutboundUrlPolicy:
    @pytest.fixture
    def policy(self) -> PublicEducationUrlPolicy:
        return PublicEducationUrlPolicy(["market.cloud.edu.tw"])

    @pytest.mark.parametrize(
        "url",
        [
            "http://market.cloud.edu.tw/x",             # 非 HTTPS
            "https://127.0.0.1/x",                      # IP 字面值
            "https://localhost/x",                      # localhost
            "https://user:pw@market.cloud.edu.tw/x",    # 內嵌憑證
            "https://evil.example.com/x",               # 目錄外主機
            "https://market.cloud.edu.tw.evil.com/x",   # 後綴混淆
            "file:///etc/passwd",                       # 非 http scheme
        ],
    )
    def test_rejected(self, policy: PublicEducationUrlPolicy, url: str) -> None:
        with pytest.raises(PolicyViolationError):
            policy.validate(url)

    def test_catalog_host_accepted(self, policy: PublicEducationUrlPolicy) -> None:
        url = "https://market.cloud.edu.tw/resource/1"
        assert policy.validate(url) == url

    def test_subdomain_of_catalog_host_accepted(
        self, policy: PublicEducationUrlPolicy
    ) -> None:
        url = "https://sub.market.cloud.edu.tw/x"
        assert policy.validate(url) == url
