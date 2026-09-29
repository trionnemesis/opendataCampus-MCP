"""HeadlessAdapter 目標 URL 的編碼與白名單回歸測試(CWE-116/CWE-74)。

修正前:`f"{official_url}?q={request.query}"` 直接插入未編碼的使用者輸入,
`&`/`#` 因此被當成 URL 語法解讀,可注入額外 query 參數或截斷 URL;
組好的 URL 也未經任何白名單驗證即交給 page.goto()。

不需安裝 playwright:build_search_url 是純函式,playwright 只在 browse() 內延遲 import。
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from opendata_campus_mcp.adapters.headless import HeadlessAdapter
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    EducationSource,
    PolicyViolationError,
)


def _source(url: str = "https://adl.edu.tw") -> EducationSource:
    return EducationSource(
        name="因材網", description="", official_url=url,
        education_stages=(), categories=(), directory_source="",
        access_strategy=AccessStrategy.HEADLESS_BROWSER,
    )


@pytest.fixture
def adapter() -> HeadlessAdapter:
    with pytest.warns(UserWarning):
        return HeadlessAdapter(enabled=True)


@pytest.mark.parametrize(
    "malicious",
    [
        "x&admin=true",              # 注入額外參數
        "x#fragment",                # 截斷 URL
        "x&q=override",              # 覆寫原參數
        "x /../../etc/passwd",
        "x?y=z",
    ],
)
def test_query_cannot_inject_url_syntax(adapter, malicious):
    url = adapter.build_search_url(_source(), malicious)
    params = parse_qs(urlparse(url).query, keep_blank_values=True)
    # 整個輸入必須完整落在單一 q 參數裡,且不得產生任何其他參數
    assert params == {"q": [malicious]}
    assert urlparse(url).fragment == ""


def test_query_is_percent_encoded(adapter):
    url = adapter.build_search_url(_source(), "數學 & 自然")
    query = urlparse(url).query
    # 原始字元不得以字面值出現在 URL 裡(否則就是未編碼)
    assert "&" not in query.removeprefix("q=")
    assert " " not in query
    assert parse_qs(query) == {"q": ["數學 & 自然"]}


def test_target_outside_catalog_is_rejected(adapter):
    with pytest.raises(PolicyViolationError):
        adapter.build_search_url(_source("https://attacker.example"), "x")


def test_non_https_target_is_rejected(adapter):
    with pytest.raises(PolicyViolationError):
        adapter.build_search_url(_source("http://adl.edu.tw"), "x")


def test_allowed_source_still_works(adapter):
    """修正不得讓合法來源失效。"""
    url = adapter.build_search_url(_source(), "數學")
    assert url.startswith("https://adl.edu.tw?q=")


def test_headless_still_disabled_by_default():
    """既有的「預設停用」不變量不得因本次修改而鬆動。"""
    with pytest.raises(RuntimeError, match="disabled by default"):
        HeadlessAdapter()
