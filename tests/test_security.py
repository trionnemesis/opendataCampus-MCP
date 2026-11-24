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
        assert MAX_RESPONSE_BYTES == 5 * 1024 * 1024

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
        with pytest.raises(ResponseTooLargeError, match="content type"):
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



# ── 6. 轉址目的地未驗證(CWE-918 SSRF,深度防禦)──────────────────────────


class TestBoundedGetRedirectPolicy:
    """`bounded_get` 的初始 URL 由呼叫端固定組出,但 `Location` 由上游決定。

    `OpenDataApiAdapter` 的 client 是 `follow_redirects=True`,而
    `bounded_get` 原本不驗證任何一跳 —— 專案花力氣建的
    `PublicEducationUrlPolicy`(拒 IP 字面值、拒非 catalog host)在這條
    路徑上完全沒被諮詢。已實測:上游回
    `Location: https://169.254.169.254/latest/meta-data/` 時,請求會被
    跟隨且 body 會原樣回傳給呼叫端。

    可利用前提:初始 URL 只有 dataset id(純數字)可控,故需上游
    data.gov.tw 自己發出轉址(被入侵、開放轉址、或 DNS/TLS 中間人)。
    MCP 用戶端無法獨立觸發 —— 列為深度防禦缺口,非可直接利用的漏洞。
    """

    _API = "https://data.gov.tw/api/v2/rest/dataset/123"

    async def test_offsite_redirect_is_rejected_before_being_requested(self) -> None:
        hops: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hops.append(str(request.url))
            if request.url.host == "data.gov.tw":
                return httpx.Response(
                    302,
                    headers={"Location": "https://169.254.169.254/latest/meta-data/"},
                )
            return httpx.Response(200, json={"leaked": True})

        async with _client(handler, follow_redirects=True) as client:
            with pytest.raises(PolicyViolationError):
                await bounded_get(
                    client, self._API,
                    allowed_content_types=None,
                    url_policy=PublicEducationUrlPolicy(["data.gov.tw"]),
                )
        # 關鍵:第二跳必須在「送出之前」就被擋下
        assert hops == [self._API]

    async def test_unknown_host_redirect_is_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "data.gov.tw":
                return httpx.Response(
                    302, headers={"Location": "https://evil.example/x"}
                )
            return httpx.Response(200, json={"leaked": True})

        async with _client(handler, follow_redirects=True) as client:
            with pytest.raises(PolicyViolationError, match="source catalog"):
                await bounded_get(
                    client, self._API,
                    allowed_content_types=None,
                    url_policy=PublicEducationUrlPolicy(["data.gov.tw"]),
                )

    async def test_same_domain_redirect_still_followed(self) -> None:
        """合法的同網域/子網域轉址(如 www.)不得被誤擋 —— 避免功能退化。"""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "data.gov.tw":
                return httpx.Response(
                    302,
                    headers={"Location": "https://www.data.gov.tw/api/v2/rest/dataset/123"},
                )
            return httpx.Response(200, json={"ok": True})

        async with _client(handler, follow_redirects=True) as client:
            resp = await bounded_get(
                client, self._API,
                allowed_content_types=None,
                url_policy=PublicEducationUrlPolicy(["data.gov.tw"]),
            )
        assert resp.json() == {"ok": True}

    async def test_no_policy_keeps_previous_behaviour(self) -> None:
        """url_policy=None 時行為不變 —— 既有呼叫端(edumarket)不受影響。"""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/a"):
                return httpx.Response(302, headers={"Location": "https://other.test/b"})
            return httpx.Response(200, json={"ok": True})

        async with _client(handler, follow_redirects=True) as client:
            resp = await bounded_get(
                client, "https://x.test/a", allowed_content_types=None
            )
        assert resp.json() == {"ok": True}


class TestOpenDataAdapterRedirectPolicy:
    """adapter 層端到端:read() 必須帶著 host policy 呼叫 bounded_get。"""

    @staticmethod
    def _adapter(handler):
        from opendata_campus_mcp.adapters.opendata import OpenDataApiAdapter

        a = OpenDataApiAdapter()
        a._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        )
        return a

    async def test_read_rejects_offsite_redirect(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "data.gov.tw":
                return httpx.Response(
                    302,
                    headers={"Location": "https://169.254.169.254/latest/meta-data/"},
                )
            return httpx.Response(
                200, json={"success": True, "result": {"title": "LEAKED"}}
            )

        a = self._adapter(handler)
        try:
            with pytest.raises(PolicyViolationError):
                await a.read("https://data.gov.tw/dataset/123", ["title"])
        finally:
            await a.aclose()

    async def test_read_still_works_without_redirect(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {
                        "title": "大專校院學生數",
                        "description": "教育部統計處",
                        "license": "1",
                        "distribution": [
                            {
                                "resourceFormat": "CSV",
                                "resourceDownloadUrl": "https://data.gov.tw/x.csv",
                            }
                        ],
                    },
                },
            )

        a = self._adapter(handler)
        try:
            out = await a.read("https://data.gov.tw/dataset/123", ["title"])
        finally:
            await a.aclose()
        assert out["title"] == "大專校院學生數"
        assert out["license"].startswith("政府資料開放授權條款")
        assert out["resources"] == [
            {"format": "CSV", "download_url": "https://data.gov.tw/x.csv"}
        ]

    def test_adapter_passes_a_policy(self) -> None:
        """防回歸:日後有人移掉 url_policy= 參數就會被抓到。"""
        src = (
            Path(__file__).resolve().parents[1]
            / "src/opendata_campus_mcp/adapters/opendata.py"
        ).read_text(encoding="utf-8")
        assert "url_policy=_HOST_POLICY" in src


# ── 7. traceparent ReDoS 依賴下限(CWE-1333)────────────────────────────────


class TestTraceparentReDoSFloor:
    """opentelemetry-api < 1.45.2 的 traceparent 解析可被用戶端輸入拖成 ReDoS。

    CVE-2026-126360 / GHSA-mf5v-w3w3-f6cg:
    `TraceContextTextMapPropagator.extract()` 的
    `^[ \t]*(..)-(..)-(..)-(..)(-.*)?[ \t]*$` 在「合法前綴 + 大量空白 +
    換行 + 尾隨字元」下,`(-.*)?` 與 `[ \t]*$` 互相回溯成二次時間。

    可達性已由程式碼確認(非推論):fastmcp 的
    `_get_parent_trace_context()`(fastmcp/server/telemetry.py)讀
    `request_ctx.get().meta` 後交給 `propagate.extract()` —— 即 MCP 請求的
    `_meta.traceparent`,完全由用戶端提供;regex 為同步呼叫,會阻塞
    asyncio 事件迴圈。1.45.2 以 512 字元上限修正。本專案無 lockfile,
    此下限用於防止新環境裝回有漏洞版本(與既有 fastmcp 下限同一作法)。
    """

    _FLOOR = "1.45.2"

    def test_pyproject_floor_excludes_vulnerable_opentelemetry(self) -> None:
        from packaging.requirements import Requirement
        from packaging.version import Version

        text = (
            Path(__file__).resolve().parents[1] / "pyproject.toml"
        ).read_text(encoding="utf-8")
        m = re.search(r'"(opentelemetry-api[^"]*)"', text)
        assert m, "opentelemetry-api floor not declared in pyproject.toml"
        req = Requirement(m.group(1))
        assert not req.specifier.contains(Version("1.45.1")), (
            "opentelemetry-api floor permits versions vulnerable to "
            "CVE-2026-126360 (traceparent ReDoS, fixed in 1.45.2)"
        )
        assert req.specifier.contains(Version(self._FLOOR))

    def test_installed_opentelemetry_meets_floor(self) -> None:
        from importlib.metadata import version

        from packaging.version import Version

        assert Version(version("opentelemetry-api")) >= Version(self._FLOOR)

    def test_oversized_traceparent_extracts_without_quadratic_blowup(self) -> None:
        """200 KB 的惡意 traceparent 必須在 1 秒內處理完。

        門檻刻意寬鬆(非精密計時):1.45.1 下同一輸入需約兩分鐘 CPU,
        1.45.2 下為毫秒級,差距約兩個數量級。
        """
        import time

        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )

        payload = "00-" + "0" * 32 + "-" + "0" * 16 + "-00-" + " " * 200_000 + "\nx"
        start = time.perf_counter()
        TraceContextTextMapPropagator().extract({"traceparent": payload})
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, (
            f"traceparent extraction took {elapsed:.1f}s — quadratic backtracking "
            "(CVE-2026-126360) appears to be present"
        )
