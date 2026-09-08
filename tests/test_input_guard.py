"""安全回歸測試 — 鎖住 MCP 工具邊界的輸入護欄。

每個 class 對應一項已確認的問題;測試同時涵蓋「攻擊/異常輸入被擋下」與
「正常輸入行為不變」兩面,避免修正造成功能退化。
"""
from __future__ import annotations

import pytest

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.input_guard import (
    MAX_QUERY_LEN,
    MAX_URL_LEN,
    clamp_count,
    validate_text,
)


# ── 1. 計數類參數下限缺失(CWE-1284)──────────────────────────────────────────


class TestCountClamping:
    """修正前只有 `min(value, upper)`,負值/0 會穿透到對外請求與切片。"""

    @pytest.mark.parametrize("bad", [-1, -100, 0])
    def test_non_positive_is_raised_to_lower_bound(self, bad: int) -> None:
        assert clamp_count(bad, 5) == 1

    def test_upper_bound_still_truncates(self) -> None:
        assert clamp_count(999, 5) == 5
        assert clamp_count(999, 20) == 20

    @pytest.mark.parametrize("ok", [1, 2, 3, 5])
    def test_in_range_values_are_unchanged(self, ok: int) -> None:
        """正常輸入必須原樣通過 — 修正不改變既有行為。"""
        assert clamp_count(ok, 5) == ok

    def test_negative_no_longer_reaches_outbound_query(self) -> None:
        """rows=-1 曾被送往教育大市集 API;夾住後最小為 1。"""
        rows = clamp_count(-1, 5)
        assert f"rows={rows}" == "rows=1"

    def test_negative_no_longer_silently_drops_a_result(self) -> None:
        """items[:-1] 曾靜默少一筆;夾住後切片語意正確。"""
        items = ["a", "b", "c", "d", "e"]
        assert items[: clamp_count(-1, 5)] == ["a"]


# ── 2. 字串長度上限缺失(CWE-400 / CWE-20)────────────────────────────────────


class TestTextLengthLimits:
    """query / source / url 會被編碼進對外請求,長度必須設限。"""

    def test_oversized_query_is_rejected(self) -> None:
        with pytest.raises(PolicyViolationError):
            validate_text("A" * (MAX_QUERY_LEN + 1), "query")

    def test_oversized_url_is_rejected(self) -> None:
        with pytest.raises(PolicyViolationError):
            validate_text("https://x/" + "A" * MAX_URL_LEN, "url", max_len=MAX_URL_LEN)

    def test_error_does_not_echo_the_input(self) -> None:
        """訊息只帶長度,不把可疑內容原樣吐回呼叫端。"""
        payload = "SENSITIVE" * 100
        with pytest.raises(PolicyViolationError) as exc_info:
            validate_text(payload, "query")
        assert "SENSITIVE" not in str(exc_info.value)

    def test_boundary_length_is_accepted(self) -> None:
        """剛好等於上限必須放行 — 邊界不可誤殺。"""
        assert validate_text("A" * MAX_QUERY_LEN, "query") == "A" * MAX_QUERY_LEN

    @pytest.mark.parametrize("ok", ["數學", "自然科學 實驗", "physics", ""])
    def test_normal_queries_pass_through_unchanged(self, ok: str) -> None:
        assert validate_text(ok, "query") == ok

    def test_none_is_passed_through(self) -> None:
        """None 代表「不過濾」,必須原樣放行。"""
        assert validate_text(None, "subject") is None


# ── 3. 工具層契約:超長輸入回既有錯誤結構,且不觸發對外請求 ────────────────────


class TestToolBoundaryContract:
    """護欄以 PolicyViolationError 回報 → 沿用既有 `policy_violated` 結構。

    公開回應格式不變(不新增例外型別給呼叫端),且必須在任何 adapter
    /網路請求之前就擋下。
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            (
                "browse_education_source",
                {"source": "因材網", "query": "A" * (MAX_QUERY_LEN + 1)},
            ),
            (
                "read_education_resource",
                {"url": "https://market.cloud.edu.tw/" + "A" * MAX_URL_LEN},
            ),
            (
                "search_exam_questions",
                {"exam_type": "學測", "subject": "A" * (MAX_QUERY_LEN + 1)},
            ),
        ],
    )
    async def test_oversized_input_returns_policy_violated(
        self, tool_name: str, arguments: dict
    ) -> None:
        from opendata_campus_mcp.mcp_server import server as server_module

        mcp = server_module.build_server()
        async with mcp._lifespan_manager():
            result = await mcp.call_tool(tool_name, arguments)

        assert result.structured_content["error"] == "policy_violated"

    @pytest.mark.asyncio
    async def test_guard_runs_before_any_adapter_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """超長 URL 不得走到 adapter — 否則等同讓呼叫端代打第三方站台。"""
        from opendata_campus_mcp.mcp_server import runtime as runtime_module
        from opendata_campus_mcp.mcp_server import server as server_module

        called = False

        class _ExplodingWebAdapter:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def browse(self, *args, **kwargs):
                nonlocal called
                called = True
                raise AssertionError("adapter must not be reached")

            async def read(self, *args, **kwargs):
                nonlocal called
                called = True
                raise AssertionError("adapter must not be reached")

            async def aclose(self) -> None:
                pass

        monkeypatch.setattr(
            runtime_module, "WebSearchAdapter", _ExplodingWebAdapter
        )
        mcp = server_module.build_server()
        async with mcp._lifespan_manager():
            result = await mcp.call_tool(
                "read_education_resource",
                {"url": "https://market.cloud.edu.tw/" + "A" * MAX_URL_LEN},
            )

        assert called is False
        assert result.structured_content["error"] == "policy_violated"
