"""安全回歸測試 — 鎖住已修正問題的觸發條件。

每個 class 對應一項已確認的問題;測試同時涵蓋「攻擊/濫用被擋下」與
「正常輸入行為不變」兩面,避免修正造成功能退化。
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from opendata_campus_mcp.contracts import (
    BrowseRequest,
    DiscoveryRequest,
    EducationSource,
    ExamSearchRequest,
    PolicyViolationError,
    ReadRequest,
)
from opendata_campus_mcp.mcp_server.runtime import build_runtime


@pytest.fixture
async def service():
    """production 組裝,但切斷 TWCampus 補充路徑 —— 本檔為離線單元測試。

    discover_sources 在本地正分不足時會補 TWCampus;此處讓它直接失敗,
    service 會靜默降級回本地目錄(既有行為),測試因此不發出任何外部請求。
    """
    runtime = build_runtime()
    service = runtime.service

    async def _offline(_request):
        raise RuntimeError("TWCampus disabled in offline unit tests")

    service._twcampus.discover = _offline  # type: ignore[method-assign]
    try:
        yield service
    finally:
        await runtime.aclose()


# ── 1. MCP 工具字串參數長度上限(CWE-20 / CWE-400)────────────────────────────


class TestInputLengthLimits:
    """超長字串會被原樣編碼進外送 URL;必須在發出請求前擋下。"""

    OVERSIZED = "ა" * 5000

    async def test_discover_rejects_oversized_query(self, service):
        with pytest.raises(PolicyViolationError, match="query too long"):
            await service.discover_sources(DiscoveryRequest(query=self.OVERSIZED))

    async def test_discover_rejects_oversized_education_stage(self, service):
        with pytest.raises(PolicyViolationError, match="education_stage too long"):
            await service.discover_sources(
                DiscoveryRequest(query="數學", education_stage=self.OVERSIZED)
            )

    async def test_browse_rejects_oversized_query(self, service):
        with pytest.raises(PolicyViolationError, match="query too long"):
            await service.browse_source(
                BrowseRequest(source_name_or_url="教育大市集", query=self.OVERSIZED)
            )

    async def test_browse_rejects_oversized_source(self, service):
        with pytest.raises(PolicyViolationError, match="source too long"):
            await service.browse_source(
                BrowseRequest(source_name_or_url=self.OVERSIZED, query="數學")
            )

    async def test_read_rejects_oversized_url(self, service):
        oversized_url = "https://market.cloud.edu.tw/" + "a" * 4000
        with pytest.raises(PolicyViolationError, match="url too long"):
            await service.read_resource(ReadRequest(url=oversized_url))

    async def test_exam_rejects_oversized_subject(self, service):
        with pytest.raises(PolicyViolationError, match="subject too long"):
            await service.search_exam_questions(
                ExamSearchRequest(exam_type="學測", subject=self.OVERSIZED)
            )

    async def test_normal_length_query_still_discovers(self, service):
        """正常輸入不受影響 —— 修正未造成功能退化。"""
        found = await service.discover_sources(DiscoveryRequest(query="國中數學"))
        assert found, "正常查詢仍應回傳平台"
        assert all("official_url" in s for s in found)

    async def test_boundary_length_query_is_accepted(self, service):
        """剛好等於上限的輸入必須通過(上限為 <=,非 <)。"""
        at_limit = "數" * 200
        found = await service.discover_sources(DiscoveryRequest(query=at_limit))
        assert isinstance(found, list)


# ── 2. headless 後備的 query 必須 percent-encode(CWE-116)────────────────────


class TestHeadlessQueryEncoding:
    """未編碼的 query 會把 & / # 送成額外參數或 fragment。

    這組測試原本在 test 內自己重寫一份 URL 組裝,等於在測一份複本;且以
    `inspect.getsource` 比對字串來守 `quote(` 是否還在。URL 組裝搬進
    `_build_search_url`(同時加上 url_policy 驗證)後,字串比對就失效了 ——
    但真正要守的性質「query 必須 percent-encode」並沒有變。
    改為直接呼叫 adapter 的真實方法並斷言行為,比字串比對更強,也不再有複本。
    """

    def _adapter(self):
        from opendata_campus_mcp.adapters.headless import HeadlessAdapter

        with pytest.warns(UserWarning):
            return HeadlessAdapter(enabled=True)

    def _search_url(self, query: str) -> str:
        """走 HeadlessAdapter 真正用來組 URL 的那條路(不啟動 Playwright)。"""
        source = EducationSource(
            name="因材網", official_url="https://adl.edu.tw/"
        )
        return self._adapter()._build_search_url(source, query)

    def test_query_is_percent_encoded_by_the_adapter(self):
        """取代原本的 inspect.getsource 字串比對:直接驗證輸出已編碼。"""
        url = self._search_url("數學&admin=1#frag")
        assert "%26admin%3D1%23frag" in url
        assert "&admin=1" not in url
        assert "#frag" not in url

    def test_injected_params_stay_inside_q_value(self):
        url = self._search_url("數學&admin=1#frag")
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        # 攻擊字串完整留在 q 內,未切出額外參數或 fragment
        assert params["q"] == ["數學&admin=1#frag"]
        assert "admin" not in params
        assert parsed.fragment == ""

    def test_normal_query_roundtrips(self):
        url = self._search_url("國中數學")
        assert parse_qs(urlparse(url).query)["q"] == ["國中數學"]

    def test_source_outside_catalog_is_refused(self):
        """_build_search_url 同時是 SSRF 邊界(PR #12 的 headless 部分)。"""
        from opendata_campus_mcp.contracts import PolicyViolationError

        evil = EducationSource(name="evil", official_url="https://evil.example")
        with pytest.raises(PolicyViolationError):
            self._adapter()._build_search_url(evil, "x")

