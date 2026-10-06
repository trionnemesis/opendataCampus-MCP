"""安全回歸測試 — 鎖住已修正問題的觸發條件。

每一組都同時涵蓋「攻擊被擋下」與「正常輸入行為不變」兩面,
避免安全修正造成功能退化。
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from opendata_campus_mcp.adapters.safe_http import (
    ALLOWED_CONTENT_TYPES,
    MAX_RESPONSE_BYTES,
    ResponseTooLargeError,
    bounded_get,
    safe_get,
)
from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_HOST = "market.cloud.edu.tw"


def _client(handler, *, follow_redirects: bool = False) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=follow_redirects
    )


def _policy() -> PublicEducationUrlPolicy:
    return PublicEducationUrlPolicy([_HOST])


# ── 1. 回應 body 大小上限(CWE-400 / CWE-770)────────────────────────────────


class TestResponseSizeLimit:
    """read_education_resource 接受 allowlist host 下的任何 URL —— 其中包含
    該站台上的大型 PDF/ZIP/影片。無上限時呼叫端(LLM)只要指向其中一個,
    就能讓 server 把數百 MB 讀進記憶體,且不需要任何權限。
    """

    async def test_oversized_body_rejected(self) -> None:
        cap = 4096
        client = _client(
            lambda request: httpx.Response(
                200, content=b"x" * (cap * 4), headers={"Content-Type": "text/html"}
            )
        )
        with pytest.raises(ResponseTooLargeError, match="exceeds"):
            await bounded_get(client, f"https://{_HOST}/big", max_bytes=cap)
        await client.aclose()

    async def test_body_at_limit_accepted(self) -> None:
        cap = 4096
        client = _client(
            lambda request: httpx.Response(
                200, content=b"y" * cap, headers={"Content-Type": "text/html"}
            )
        )
        resp = await bounded_get(client, f"https://{_HOST}/exact", max_bytes=cap)
        assert len(resp.content) == cap
        await client.aclose()

    async def test_safe_get_enforces_the_same_limit(self) -> None:
        """url_policy / browser_policy 路徑也受大小上限保護。"""
        cap = 4096
        client = _client(
            lambda request: httpx.Response(
                200, content=b"z" * (cap * 4), headers={"Content-Type": "text/html"}
            )
        )
        with pytest.raises(ResponseTooLargeError):
            await safe_get(
                client,
                f"https://{_HOST}/big",
                url_policy=_policy(),
                browser_policy=BrowserPolicy(),
                max_bytes=cap,
            )
        await client.aclose()

    def test_default_cap_is_set_and_bounded(self) -> None:
        assert 0 < MAX_RESPONSE_BYTES <= 64 * 1024 * 1024

    async def test_error_is_a_policy_violation(self) -> None:
        """ResponseTooLargeError 必須是 PolicyViolationError 的子類 ——
        MCP 工具層已有該型別的處理分支,否則會變成未處理例外。"""
        assert issubclass(ResponseTooLargeError, PolicyViolationError)


# ── 2. Content-Type 白名單(只接受可解析的文字)──────────────────────────────


class TestContentTypeAllowlist:
    @pytest.mark.parametrize(
        "media_type",
        ["application/pdf", "application/zip", "video/mp4", "image/png",
         "application/octet-stream"],
    )
    async def test_binary_content_type_rejected(self, media_type: str) -> None:
        client = _client(
            lambda request: httpx.Response(
                200, content=b"binary", headers={"Content-Type": media_type}
            )
        )
        with pytest.raises(ResponseTooLargeError, match="content-type"):
            await bounded_get(client, f"https://{_HOST}/file")
        await client.aclose()

    @pytest.mark.parametrize("media_type", ALLOWED_CONTENT_TYPES)
    async def test_text_content_types_accepted(self, media_type: str) -> None:
        client = _client(
            lambda request: httpx.Response(
                200, content=b"{}", headers={"Content-Type": f"{media_type}; charset=utf-8"}
            )
        )
        resp = await bounded_get(client, f"https://{_HOST}/page")
        assert resp.status_code == 200
        await client.aclose()

    async def test_missing_content_type_is_not_blocked(self) -> None:
        """部分政府站台不送 Content-Type;此時仍有大小上限兜底。"""
        client = _client(lambda request: httpx.Response(200, content=b"<html></html>"))
        resp = await bounded_get(client, f"https://{_HOST}/nohdr")
        assert resp.text == "<html></html>"
        await client.aclose()

    async def test_error_pages_are_not_content_type_checked(self) -> None:
        """錯誤頁 body 不會被下游解析,型別不該成為第二種失敗原因。"""
        client = _client(
            lambda request: httpx.Response(
                503, content=b"down", headers={"Content-Type": "application/pdf"}
            )
        )
        resp = await bounded_get(client, f"https://{_HOST}/err")
        assert resp.status_code == 503
        await client.aclose()

    async def test_fixed_endpoint_apis_can_opt_out(self) -> None:
        """固定端點的 JSON API 以 allowed_content_types=None 只保留大小上限。"""
        client = _client(
            lambda request: httpx.Response(
                200, content=b"{}", headers={"Content-Type": "text/json"}
            )
        )
        resp = await bounded_get(
            client, f"https://{_HOST}/api", allowed_content_types=None
        )
        assert resp.json() == {}
        await client.aclose()


# ── 3. 既有行為不變(回傳的仍是可用的 httpx.Response)──────────────────────


class TestBoundedGetPreservesResponseApi:
    async def test_text_json_and_status_still_work(self) -> None:
        client = _client(
            lambda request: httpx.Response(
                200, json={"a": 1}, headers={"Content-Type": "application/json"}
            )
        )
        resp = await bounded_get(client, f"https://{_HOST}/x")
        assert resp.status_code == 200
        assert resp.json() == {"a": 1}
        assert resp.text == '{"a":1}'
        await client.aclose()

    async def test_safe_get_still_validates_and_follows_redirects(self) -> None:
        hops: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hops.append(str(request.url))
            if request.url.path == "/start":
                return httpx.Response(302, headers={"Location": f"https://{_HOST}/end"})
            return httpx.Response(200, content=b"ok", headers={"Content-Type": "text/html"})

        client = _client(handler)
        resp = await safe_get(
            client,
            f"https://{_HOST}/start",
            url_policy=_policy(),
            browser_policy=BrowserPolicy(),
        )
        assert resp.text == "ok"
        assert len(hops) == 2
        await client.aclose()

    async def test_safe_get_still_rejects_offsite_redirects(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://evil.example/x"})

        client = _client(handler)
        with pytest.raises(PolicyViolationError, match="source catalog"):
            await safe_get(
                client,
                f"https://{_HOST}/start",
                url_policy=_policy(),
                browser_policy=BrowserPolicy(),
            )
        await client.aclose()


# ── 4. 每個 adapter 都必須走 bounded_get(結構性回歸防護)────────────────────


class TestAllAdaptersAreBounded:
    """避免日後新增或改回 self._client.get(),讓某條路徑重新變成無上限。"""

    _ADAPTERS = [
        "twcampus.py",
        "ceec_exam.py",
        "edumarket.py",
        "opendata.py",
        "web_search.py",
    ]

    @pytest.mark.parametrize("filename", _ADAPTERS)
    def test_no_raw_client_get(self, filename: str) -> None:
        path = Path("src/opendata_campus_mcp/adapters") / filename
        text = path.read_text(encoding="utf-8")
        raw = re.findall(r"await self\._client\.get\(", text)
        assert raw == [], (
            f"{filename} 直接呼叫 self._client.get() —— 回應大小無上限(CWE-400),"
            " 請改走 safe_http.bounded_get / safe_get"
        )

    @pytest.mark.parametrize("filename", _ADAPTERS)
    def test_goes_through_safe_http(self, filename: str) -> None:
        path = Path("src/opendata_campus_mcp/adapters") / filename
        text = path.read_text(encoding="utf-8")
        assert "safe_http import" in text and (
            "bounded_get(" in text or "safe_get(" in text
        )


# ── 5. 相依套件下限不得允許已知有漏洞的 fastmcp ────────────────────────────


class TestFastMcpDependencyFloor:
    """fastmcp < 3.2.0 受 PYSEC-2026-2475 / PYSEC-2026-2476 影響
    (CVE-2026-32871:OpenAPI provider 的 buildurl() 未轉義 path 參數 →
    SSRF / path traversal)。本專案不走該程式路徑,但 floor 不應允許
    全新環境裝進已知有漏洞的版本。
    """

    def test_floor_excludes_vulnerable_fastmcp(self) -> None:
        from packaging.requirements import Requirement
        from packaging.version import Version

        text = Path("pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'"(fastmcp[^"]*)"', text)
        assert m, "pyproject.toml 找不到 fastmcp 相依宣告"
        req = Requirement(m.group(1))
        assert not req.specifier.contains(Version("3.1.0"))
        assert req.specifier.contains(Version("3.2.0"))

    def test_installed_fastmcp_meets_floor(self) -> None:
        from importlib.metadata import version

        from packaging.version import Version

        assert Version(version("fastmcp")) >= Version("3.2.0")


# ── 6. CI 必須有 SAST / SCA gate 與最小權限 ──────────────────────────────────


@pytest.fixture(scope="module")
def ci() -> str:
    return Path(".github/workflows/ci.yml").read_text(encoding="utf-8")


class TestCiSecurityGates:
    def test_has_least_privilege_token(self, ci: str) -> None:
        assert re.search(r"^permissions:\s*$", ci, flags=re.MULTILINE)
        assert "contents: read" in ci

    @pytest.mark.parametrize("tool", ["bandit", "pip_audit"])
    def test_has_security_job(self, ci: str, tool: str) -> None:
        assert f"python -m {tool}" in ci

    def test_no_inputs_interpolated_into_run_blocks(self, ci: str) -> None:
        """${{ }} 在 shell 執行前做文字替換;插進 run: 等於讓輸入變成 shell 語法。"""
        offenders = [
            line.strip()
            for line in ci.splitlines()
            if "${{" in line and ("inputs." in line or "github.event" in line)
        ]
        assert offenders == [], offenders
