"""MCP 工具參數的長度/範圍護欄 — 純函式,零 I/O。

為什麼需要:工具參數會被接進外送 URL(`quote(query)` 進 edumarket path、
`url` 進 read_resource)與本地分詞計分。先前完全沒有長度上限,
httpx 的 65536-byte URL 上限成了實際的唯一邊界,而超過時丟的是
`httpx.InvalidURL` —— 它不是 `httpx.TransportError`,adapter 的
`except httpx.TransportError` 接不到,例外會直接穿出工具(CWE-20 / CWE-1284)。

上限取遠大於任何真實查詢的值,正常使用不受影響。
姊妹專案 g0vmcp(`_validate_str`)與 hcmcp(`_check_len`)已有同類護欄,
本模組補上本專案缺的那一份。
"""
from __future__ import annotations

MAX_QUERY_LEN = 500
MAX_FIELD_LEN = 100
MAX_SOURCE_LEN = 500
# 2048 是實務上各家瀏覽器/伺服器共同支援的 URL 長度下限
MAX_URL_LEN = 2048


class InputValidationError(ValueError):
    """工具參數超出長度或範圍上限。"""


def check_len(value: str | None, *, name: str, max_len: int) -> None:
    """value 超過 max_len 時丟 InputValidationError。None 視為未提供,直接通過。"""
    if value is not None and len(value) > max_len:
        raise InputValidationError(
            f"{name} too long ({len(value)} chars, max {max_len})"
        )


def clamp_count(value: int, *, max_value: int) -> int:
    """把筆數上限正規化到 1..max_value。

    先前只有 `min(value, max_value)`,沒有下界:max_results=-1 會被原樣帶進
    edumarket 的 `rows=-1` 送給上游 API,其他 adapter 則因 `len(x) >= -1`
    立刻為真而回傳空集合 —— 兩者都不是呼叫端預期的行為。
    """
    return max(1, min(int(value), max_value))
