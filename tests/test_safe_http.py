"""safe_http 安全回歸測試 — SEC-3(redirect SSRF)與 SEC-4(回應大小/型別)。

每個測試對應一個先前可被觸發的攻擊路徑;離線執行(httpx.MockTransport),
不需網路,故可進 CI gate。
"""
from __future__ import annotations

import httpx
import pytest

from opendata_campus_mcp.adapters.safe_http import (
    MAX_RESPONSE_BYTES,
    safe_get,
)
from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

ALLOWED = "https://data.gov.tw/x"
_POLICY = PublicEducationUrlPolicy(["data.gov.tw"])


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── SEC-3:redirect 逐跳驗證(CWE-918)────────────────────────────────────────

@pytest.mark.parametrize(
    "target",
    [
        "http://169.254.169.254/latest/meta-data/",  # 雲端 metadata
        "https://127.0.0.1:8000/admin",              # loopback
        "https://localhost/admin",
        "https://attacker.example/steal",            # 白名單外網域
        "file:///etc/passwd",                        # 非 HTTPS scheme
    ],
)
async def test_redirect_to_internal_or_unknown_target_is_blocked(target):
    """上游 open redirect 不得把請求帶往內部位址或白名單外網域。"""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == ALLOWED:
            return httpx.Response(302, headers={"Location": target})
        return httpx.Response(200, text="SHOULD NOT BE REACHED")

    with pytest.raises(PolicyViolationError):
        await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)

    # 關鍵斷言:被拒的目標「從未被請求」——驗證發生在送出請求之前
    assert requested == [ALLOWED]


async def test_allowed_same_host_redirect_still_followed():
    """同網域 redirect 仍須正常跟隨 —— 修正不得破壞既有取得資料的能力。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/x":
            return httpx.Response(301, headers={"Location": "/final"})
        return httpx.Response(200, text="ok", headers={"Content-Type": "text/html"})

    resp = await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)
    assert resp.status_code == 200
    assert resp.text == "ok"


async def test_redirect_loop_is_bounded():
    """無 browser_policy 時仍不得被無限 redirect 迴圈拖住。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/next"})

    with pytest.raises(PolicyViolationError, match="redirect"):
        await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)


# ── SEC-4:回應大小與 Content-Type(CWE-400/CWE-770)──────────────────────────

async def test_oversized_body_is_rejected():
    """超過上限的 body 不得被讀進記憶體並交給 parser。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"A" * (MAX_RESPONSE_BYTES + 1),
            headers={"Content-Type": "text/html"},
        )

    with pytest.raises(PolicyViolationError, match="exceeds"):
        await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)


async def test_lying_content_length_still_bounded():
    """Content-Length 造假(宣告很小、實際很大)時,逐塊檢查仍須攔下。"""
    big = b"A" * (MAX_RESPONSE_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        resp = httpx.Response(200, content=big, headers={"Content-Type": "text/html"})
        resp.headers["Content-Length"] = "10"  # 謊報
        return resp

    with pytest.raises(PolicyViolationError, match="exceeds"):
        await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)


async def test_body_within_limit_is_returned_intact():
    """未超限的回應內容必須逐位元組保持原樣(串流重組不得損壞 body)。"""
    payload = "中文內容 " * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=payload,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    resp = await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)
    assert resp.text == payload


async def test_json_response_still_parses():
    """JSON adapter(opendata/edumarket)依賴 .json();重組後須仍可解析。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "result": {"a": 1}})

    resp = await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)
    assert resp.json() == {"success": True, "result": {"a": 1}}


@pytest.mark.parametrize(
    "media_type", ["application/octet-stream", "image/png", "video/mp4"]
)
async def test_non_text_content_type_is_rejected(media_type):
    """二進位內容不得被餵進 HTML parser。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x00\x01", headers={"Content-Type": media_type})

    with pytest.raises(PolicyViolationError, match="content type"):
        await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)


async def test_missing_content_type_is_allowed():
    """部分政府站台不送 Content-Type;缺標頭不應成為新的失敗來源。"""
    def handler(request: httpx.Request) -> httpx.Response:
        resp = httpx.Response(200, text="ok")
        del resp.headers["Content-Type"]
        return resp

    resp = await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)
    assert resp.status_code == 200


async def test_redirect_content_type_not_enforced():
    """3xx 的 body 不會被解析,其 Content-Type 不該讓合法 redirect 失敗。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/x":
            return httpx.Response(
                302,
                headers={"Location": "/final", "Content-Type": "application/octet-stream"},
            )
        return httpx.Response(200, text="ok", headers={"Content-Type": "text/html"})

    resp = await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)
    assert resp.text == "ok"


# ── browser_policy 為選用(自帶速率控制的 adapter 不得被重複計數)──────────────

async def test_browser_policy_is_optional_and_not_double_counted():
    """不傳 browser_policy 時,預算不得被消耗(否則 ceec 分頁會誤觸上限)。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok", headers={"Content-Type": "text/html"})

    policy = BrowserPolicy()
    for _ in range(policy.max_requests_per_minute + 2):
        await safe_get(_client(handler), ALLOWED, url_policy=_POLICY)
    # 預算未被動用 → 呼叫端自己的計數仍是唯一來源
    assert policy._windows == {}


async def test_browser_policy_still_enforced_when_supplied():
    """傳入 browser_policy 時,既有的速率限制行為必須保持不變。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok", headers={"Content-Type": "text/html"})

    from opendata_campus_mcp.contracts import RateLimitError
    policy = BrowserPolicy()
    client = _client(handler)
    for _ in range(policy.max_requests_per_minute):
        await safe_get(client, ALLOWED, url_policy=_POLICY, browser_policy=policy)
    with pytest.raises(RateLimitError):
        await safe_get(client, ALLOWED, url_policy=_POLICY, browser_policy=policy)
