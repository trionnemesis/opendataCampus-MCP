"""HeadlessAdapter 的搜尋 URL 組裝 —— query 必須是資料,不是 URL 語法。

headless 預設停用(需顯式 enabled=True),故這裡只測純函式的 URL 組裝,
不需要 playwright。
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from opendata_campus_mcp.adapters.headless import HeadlessAdapter, _build_search_url


class TestSearchUrlEncoding:
    @pytest.mark.parametrize(
        ("query", "expected_q"),
        [
            # & 原本會被當成參數分隔,讓呼叫端多塞一個 admin=1
            ("math&admin=1", "math&admin=1"),
            # # 原本會把後半段切成 fragment,實際請求的路徑因此被改掉
            ("math#/../../etc", "math#/../../etc"),
            # ? 與 = 同樣是 URL 結構字元
            ("a?b=c", "a?b=c"),
            ("國小 數學", "國小 數學"),
            ("plain", "plain"),
        ],
    )
    def test_query_survives_as_a_single_parameter(self, query, expected_q) -> None:
        url = _build_search_url("https://adl.edu.tw/", query)
        parsed = urlparse(url)
        assert parsed.hostname == "adl.edu.tw"
        assert parsed.fragment == ""  # # 已被編碼,不會產生 fragment
        params = parse_qs(parsed.query, keep_blank_values=True)
        assert list(params) == ["q"], f"多出非預期的查詢參數: {params}"
        assert params["q"] == [expected_q]

    def test_existing_query_string_uses_ampersand(self) -> None:
        url = _build_search_url("https://adl.edu.tw/search?lang=zh", "math")
        assert url == "https://adl.edu.tw/search?lang=zh&q=math"

    def test_trailing_slash_is_stripped(self) -> None:
        assert _build_search_url("https://adl.edu.tw/", "x") == "https://adl.edu.tw?q=x"


class TestStillDisabledByDefault:
    """修正不得放寬「預設停用」這道既有護欄。"""

    def test_requires_explicit_enable(self) -> None:
        with pytest.raises(RuntimeError, match="disabled by default"):
            HeadlessAdapter()
