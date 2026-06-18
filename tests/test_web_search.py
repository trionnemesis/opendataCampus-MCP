"""WebSearchAdapter._extract_fields 結構化欄位萃取測試（直接餵 HTML head，離線）。

驗證 _meta helper 的 case-insensitive + 空值視為 miss + 各欄位萃取順序;
誠實確認 keyword 不當 subject、無 educationLevel meta 時 stage 為 None。
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from opendata_campus_mcp.adapters.web_search import WebSearchAdapter

_EXTRACT = ["title", "summary", "publisher", "education_stage", "subject", "license"]
# 繞過 __init__（不建 httpx client）；_extract_fields 不依賴實例屬性
_ADAPTER = WebSearchAdapter.__new__(WebSearchAdapter)


def _extract(head_html: str) -> dict:
    soup = BeautifulSoup(f"<html><head>{head_html}</head><body></body></html>", "html.parser")
    return _ADAPTER._extract_fields(soup, "https://x.edu.tw/r/1", _EXTRACT)


def test_dc_head_empty_values_are_miss():
    r = _extract(
        '<meta name="DC.Publisher" content="國立公共資訊圖書館">'
        '<meta name="DC.Subject" content="">'
        '<meta name="DC.Rights" content="">'
    )
    assert r["publisher"] == "國立公共資訊圖書館"
    assert r["subject"] is None   # 空字串視為 miss
    assert r["license"] is None   # 空字串視為 miss
    assert r["education_stage"] is None


def test_og_head_publisher_from_site_name():
    r = _extract('<meta property="og:site_name" content="均一教育平台">')
    assert r["publisher"] == "均一教育平台"
    assert r["education_stage"] is None
    assert r["subject"] is None
    assert r["license"] is None


def test_keyword_only_head_has_no_subject():
    r = _extract('<meta name="keywords" content="學測,會考,高中"><meta name="description" content="站台簡介文字足夠長以通過門檻共三十餘字節範例範例">')
    assert r["subject"] is None          # keyword 不當 subject
    assert r["education_stage"] is None
    assert r["license"] is None


def test_license_from_link_rel():
    r = _extract('<link rel="license" href="https://creativecommons.org/licenses/by/4.0/">')
    assert r["license"] == "https://creativecommons.org/licenses/by/4.0/"


def test_dc_rights_case_insensitive():
    r = _extract('<meta name="DC.Rights" content="CC BY-NC">')
    assert r["license"] == "CC BY-NC"   # 大小寫不敏感命中（修正舊 dc.rights 比不到 DC.Rights）


def test_dc_subject_nonempty():
    r = _extract('<meta name="DC.Subject" content="數學">')
    assert r["subject"] == "數學"
