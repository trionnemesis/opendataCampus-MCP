"""MCP 工具邊界的輸入護欄 — 純函式,零 I/O。

不變量:工具參數在建立 Request 物件前就必須落在合法範圍,
理由是這些值會被編碼進對外請求(官方教育平台 URL / query),
未設限的輸入等同讓呼叫端代為對第三方站台施壓。

兩類護欄:
  - validate_text:字串長度上限(CWE-400 資源耗用)
  - clamp_count  :計數類上下限(CWE-1284 數量驗證不當)

計數類刻意「夾住」而非拋錯:上限本來就是靜默截斷(既有行為),
下限補齊後語意一致 — 負值不再穿透到 `rows=-1` 這類對外參數。
"""
from __future__ import annotations

from opendata_campus_mcp.contracts import PolicyViolationError

# 教育平台搜尋關鍵字;200 與 g0vmcp TenderQueryService._MAX_INPUT_LEN 對齊
MAX_QUERY_LEN = 200
# 平台名稱或官方 URL(find_by_name / find_by_url 皆為精確比對,不需更長)
MAX_SOURCE_LEN = 2048
# 資源頁 URL;2048 為主流瀏覽器/伺服器的實務 URL 上限
MAX_URL_LEN = 2048


def validate_text(
    value: str | None, name: str, *, max_len: int = MAX_QUERY_LEN
) -> str | None:
    """長度超標則拋 PolicyViolationError;None 直接放行(代表「不過濾」)。

    以 PolicyViolationError 而非 ValueError 回報,是為了讓既有工具的
    `except PolicyViolationError` 直接接住 — 公開錯誤結構不變。
    錯誤訊息只帶長度,不回放原始輸入(避免把可疑內容再吐回呼叫端)。
    """
    if value is not None and len(value) > max_len:
        raise PolicyViolationError(
            f"{name} too long ({len(value)} chars, max {max_len})"
        )
    return value


def clamp_count(value: int, upper: int, *, lower: int = 1) -> int:
    """將計數類參數夾到 [lower, upper]。

    既有行為只做 `min(value, upper)`,負值與 0 會穿透:
    -1 會變成對外 API 的 `rows=-1`,也會讓 `items[:-1]` 靜默少一筆。
    """
    return max(lower, min(int(value), upper))
