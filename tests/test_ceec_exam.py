"""CeecExamAdapter 單元測試 — httpx.MockTransport 模擬 CEEC listing（離線）。

涵蓋：table→ExamQuestionResult 映射、一列多 PDF 攤平、全形/半形 dash 與括號的
年份/科目解析、malformed title fallback、非 file_pool 連結跳過、download_url 前綴、
year/subject filter、未知 exam_type、max_results clamp、去重、翻頁、page/rate limit、錯誤對應。
"""
from __future__ import annotations

import httpx
import pytest

from opendata_campus_mcp.adapters.ceec_exam import CeecExamAdapter
from opendata_campus_mcp.contracts import (
    ExamSearchRequest,
    LoginRequiredError,
    RateLimitError,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy

# 模仿真實 CEEC listing：5 個資料列 + 1 個導覽列（非 file_pool，應跳過）
_LISTING_HTML = """
<table>
<tr><th>日期</th><th>標題</th><th>下載</th></tr>
<tr>
  <td>115-02-23</td>
  <td>115學年度學科能力測驗－數學A</td>
  <td>
    <a href="/files/file_pool/1/aaa/03-115數學a試卷.pdf" title="03-115學測數學A試卷">試題內容</a>
    <a href="/files/file_pool/1/bbb/03-115數學a試卷.docx" title="03-115學測數學A試卷">試題內容</a>
    <a href="/files/file_pool/1/ccc/03-115數學a答題卷.pdf" title="03-115學測數學A答題卷">答題卷</a>
    <a href="/files/file_pool/1/ddd/03-115數學a答案.pdf" title="03-115學測數學A答案">選擇題答案</a>
    <a href="/files/file_pool/1/eee/115數學a評分.pdf" title="115學測數學A非選擇題參考答案與評分原則">非選擇題評分原則</a>
  </td>
</tr>
<tr>
  <td>114-01-20</td>
  <td>114學年度學科能力測驗-英文</td>
  <td>
    <a href="/files/file_pool/1/fff/02-114英文試卷.pdf" title="02-114學測英文試卷">試題內容</a>
    <a href="/files/file_pool/1/ggg/02-114英文答案.pdf" title="02-114學測英文答案">選擇題答案</a>
  </td>
</tr>
<tr>
  <td>113-02-01</td>
  <td>113學年度學科能力測驗－數學A（補考）</td>
  <td><a href="/files/file_pool/1/hhh/數學a.pdf" title="113數學A試卷">試題內容</a></td>
</tr>
<tr>
  <td>112-01-01</td>
  <td>沒有學年度格式的標題</td>
  <td><a href="/files/file_pool/1/iii/x.pdf" title="某科試卷">試題內容</a></td>
</tr>
<tr>
  <td>導覽</td><td>關於我們</td><td><a href="/about">關於</a></td>
</tr>
</table>
"""


def _ok(html: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)
    return handler


def _adapter(handler, policy: BrowserPolicy | None = None) -> CeecExamAdapter:
    a = CeecExamAdapter(policy or BrowserPolicy())
    a._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return a


@pytest.mark.asyncio
async def test_maps_table_to_results():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", max_results=20))
    assert len(res) == 9  # row 5+2+1+1；導覽列跳過
    assert all(r.exam_type == "學測" for r in res)


@pytest.mark.asyncio
async def test_row_with_multiple_pdfs_expands():
    res = await _adapter(_ok(_LISTING_HTML)).search(
        ExamSearchRequest("學測", year="115", subject="數學A", max_results=20))
    assert len(res) == 5
    assert all(r.year == "115" and r.subject == "數學A" for r in res)
    assert [r.paper_type for r in res] == ["試題", "試題", "其他", "答案", "答案"]


@pytest.mark.asyncio
async def test_fullwidth_dash_parse():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", year="115", max_results=20))
    assert res[0].year == "115" and res[0].subject == "數學A"


@pytest.mark.asyncio
async def test_halfwidth_dash_parse():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", subject="英文", max_results=20))
    assert res and all(r.subject == "英文" and r.year == "114" for r in res)


@pytest.mark.asyncio
async def test_subject_strips_paren():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", year="113", max_results=20))
    assert res and res[0].subject == "數學A"  # （補考）被砍


@pytest.mark.asyncio
async def test_malformed_title_keeps_fallback():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", max_results=20))
    bad = [r for r in res if r.year == ""]
    assert bad and bad[0].title == "某科試卷"  # title 保留，不丟筆


@pytest.mark.asyncio
async def test_skips_non_filepool_links():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", max_results=20))
    assert all("/files/file_pool/" in r.download_url for r in res)
    assert all("關於" not in r.title for r in res)


@pytest.mark.asyncio
async def test_download_url_absolute():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", max_results=20))
    assert all(r.download_url.startswith("https://www.ceec.edu.tw/files/file_pool/") for r in res)


@pytest.mark.asyncio
async def test_paper_type_classification():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", year="115", max_results=20))
    assert any(r.paper_type == "其他" and "答題卷" in r.title for r in res)
    assert any(r.paper_type == "答案" for r in res)
    assert any(r.paper_type == "試題" for r in res)


@pytest.mark.asyncio
async def test_year_filter():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", year="114", max_results=20))
    assert res and all(r.year == "114" for r in res)


@pytest.mark.asyncio
async def test_subject_filter():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("學測", subject="英文", max_results=20))
    assert res and all("英文" in r.subject for r in res)


@pytest.mark.asyncio
async def test_unknown_exam_type_returns_empty():
    res = await _adapter(_ok(_LISTING_HTML)).search(ExamSearchRequest("會考", max_results=20))
    assert res == []


@pytest.mark.asyncio
async def test_max_results_clamps_and_single_page():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=_LISTING_HTML)

    res = await _adapter(handler).search(ExamSearchRequest("學測", max_results=2))
    assert len(res) == 2
    assert calls["n"] == 1  # 第 1 頁就滿足，不抓第 2 頁


@pytest.mark.asyncio
async def test_dedup_same_url():
    dup = (
        '<table><tr><td>115-01-01</td><td>115學年度學科能力測驗－國綜</td>'
        '<td><a href="/files/file_pool/1/x/a.pdf" title="a試卷">試題內容</a>'
        '<a href="/files/file_pool/1/x/a.pdf" title="a試卷">試題內容</a></td></tr></table>'
    )
    res = await _adapter(_ok(dup)).search(ExamSearchRequest("學測", max_results=20))
    assert len(res) == 1  # 相同 download_url 去重


@pytest.mark.asyncio
async def test_pagination_fetches_page2():
    page1 = (
        '<table><tr><td>115-01-01</td><td>115學年度學科能力測驗－地科</td>'
        '<td><a href="/files/file_pool/1/p1/a.pdf" title="地科試卷">試題內容</a></td></tr></table>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        return httpx.Response(200, text=page1 if page == "1" else _LISTING_HTML)

    res = await _adapter(handler).search(ExamSearchRequest("學測", max_results=20))
    assert len(res) == 10  # page1=1 + page2=9


@pytest.mark.asyncio
async def test_page_limit_caps_at_two_pages_no_raise():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        html = (
            f'<table><tr><td>99-01-01</td><td>99學年度學科能力測驗－冷門{calls["n"]}</td>'
            f'<td><a href="/files/file_pool/1/z{calls["n"]}/a.pdf" title="x">試題內容</a></td></tr></table>'
        )
        return httpx.Response(200, text=html)

    # filter 一個不存在的 subject → 逼翻頁；最多 2 頁後優雅停止（不 raise）
    res = await _adapter(handler).search(ExamSearchRequest("學測", subject="不存在科目", max_results=20))
    assert calls["n"] == 2 and res == []


@pytest.mark.asyncio
async def test_rate_limit_raises():
    policy = BrowserPolicy()
    for _ in range(3):  # 撐滿 www.ceec.edu.tw 配額
        policy.check_rate_limit("www.ceec.edu.tw")
    with pytest.raises(RateLimitError):
        await _adapter(_ok(_LISTING_HTML), policy).search(ExamSearchRequest("學測"))


@pytest.mark.asyncio
async def test_transport_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fail")
    with pytest.raises(SourceUnavailableError):
        await _adapter(handler).search(ExamSearchRequest("學測"))


@pytest.mark.asyncio
async def test_http_500_raises_unavailable():
    with pytest.raises(SourceUnavailableError):
        await _adapter(lambda r: httpx.Response(500)).search(ExamSearchRequest("學測"))


@pytest.mark.asyncio
async def test_http_403_raises_login_required():
    with pytest.raises(LoginRequiredError):
        await _adapter(lambda r: httpx.Response(403)).search(ExamSearchRequest("學測"))


@pytest.mark.asyncio
async def test_empty_table_returns_empty():
    res = await _adapter(_ok("<table></table>")).search(ExamSearchRequest("學測", max_results=20))
    assert res == []
