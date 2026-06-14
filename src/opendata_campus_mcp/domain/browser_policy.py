"""BrowserPolicy — TWCampus 瀏覽行為護欄。

不變量（對應 spec/features/browser-policy.feature）：
  1. 每分鐘同域請求次數 ≤ max_requests_per_minute（3）
  2. 每次工具呼叫開啟頁面數 ≤ max_pages_per_request（2）
  3. 不遞迴導航；不排程爬取
  4. 計數器以 domain 為 key，各域獨立
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from opendata_campus_mcp.contracts import PolicyViolationError, RateLimitError

_WINDOW_SECONDS = 60


class BrowserPolicy:
    max_pages_per_request: int = 2
    max_requests_per_minute: int = 3
    scheduled_crawling: bool = False
    recursive_navigation: bool = False

    def __init__(self) -> None:
        # domain → list of request timestamps within current window
        self._windows: dict[str, list[datetime]] = defaultdict(list)

    def check_rate_limit(self, domain: str) -> None:
        """呼叫成功計入一次請求；超出限制則拋出 RateLimitError。"""
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=_WINDOW_SECONDS)
        self._windows[domain] = [t for t in self._windows[domain] if t > cutoff]
        if len(self._windows[domain]) >= self.max_requests_per_minute:
            raise RateLimitError(
                f"rate limit exceeded for {domain}: "
                f"max {self.max_requests_per_minute} req/{_WINDOW_SECONDS}s"
            )
        self._windows[domain].append(now)

    def check_page_limit(self, pages_used: int) -> None:
        """在開啟新頁面前呼叫；pages_used 達上限則拋出 PolicyViolationError。"""
        if pages_used >= self.max_pages_per_request:
            raise PolicyViolationError(
                f"max_pages_per_request={self.max_pages_per_request} exceeded "
                f"(pages_used={pages_used})"
            )
