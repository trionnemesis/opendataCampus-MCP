"""跨層 DTO、Enum、Protocol — DI 邊界。

所有層只依賴本模組型別；新增平台來源 = 實作 SourceAdapter Protocol。
設計延續 healthcare-opendata-mcp 的 contracts 哲學：型別即文件。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol


class AccessStrategy(enum.Enum):
    """存取策略；數字為路由優先序（越小越優先）。"""

    OFFICIAL_API = "OFFICIAL_API"        # priority 0
    OPEN_DATA = "OPEN_DATA"              # priority 1
    WEB_SEARCH = "WEB_SEARCH"            # priority 2
    TWCAMPUS_DIRECTORY = "TWCAMPUS_DIRECTORY"  # priority 3
    HEADLESS_BROWSER = "HEADLESS_BROWSER"      # priority 4 — 預設停用

    @property
    def priority(self) -> int:
        return {
            "OFFICIAL_API": 0,
            "OPEN_DATA": 1,
            "WEB_SEARCH": 2,
            "TWCAMPUS_DIRECTORY": 3,
            "HEADLESS_BROWSER": 4,
        }[self.value]


@dataclass(frozen=True)
class EducationSource:
    """已知或已發現的官方教育平台。Aggregate Root。"""

    name: str
    official_url: str
    description: str = ""
    categories: tuple[str, ...] = ()
    education_stages: tuple[str, ...] = ()
    access_strategy: AccessStrategy = AccessStrategy.WEB_SEARCH
    directory_source: str = "TWCampus"


@dataclass(frozen=True)
class SearchResult:
    """browse_education_source 回傳的單筆搜尋結果。Value Object。"""

    title: str
    url: str
    summary: str
    source_name: str
    source_url: str
    education_stage: str | None = None
    subject: str | None = None
    publisher: str | None = None


@dataclass(frozen=True)
class ResourceDetail:
    """read_education_resource 回傳的資源摘要。Value Object。"""

    url: str
    title: str
    summary: str
    publisher: str | None = None
    education_stage: str | None = None
    subject: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class ExamQuestionResult:
    """search_exam_questions 回傳的單筆考題連結。Value Object。

    只承載官方試題的下載連結與 metadata；不下載、不儲存 PDF 全文。
    """

    exam_type: str          # 學測 / 分科測驗
    year: str               # 民國年字串，如 "115"（解析失敗為 ""）
    subject: str            # 科目，如 國綜 / 英文 / 數學A
    paper_type: str         # 試題 / 答案 / 其他
    title: str              # 檔案層級標題（如「01-115學測國綜試卷」），永遠保留
    download_url: str       # 絕對 URL（多為 PDF，CEEC 部分另提供 .docx 等格式）
    source: str             # 來源站名 + listing URL（出處可追溯）
    published: str | None = None   # 公告日期，如 "115-02-23"


@dataclass(frozen=True)
class DiscoveryRequest:
    query: str
    education_stage: str | None = None
    subject: str | None = None
    max_sources: int = 3


@dataclass(frozen=True)
class BrowseRequest:
    source_name_or_url: str
    query: str
    max_results: int = 5


@dataclass(frozen=True)
class ReadRequest:
    url: str
    extract: tuple[str, ...] = (
        "title", "summary", "publisher",
        "education_stage", "subject", "license",
    )


@dataclass(frozen=True)
class ExamSearchRequest:
    exam_type: str                 # 學測 / 分科測驗
    year: str | None = None        # 民國年過濾，None = 不限
    subject: str | None = None     # 科目過濾，None = 不限
    max_results: int = 10


# ──────────────────────────────────────────
# Domain Errors
# ──────────────────────────────────────────

class PolicyViolationError(RuntimeError):
    """超出瀏覽器政策限制（頁面數或遞迴導航）。"""


class RateLimitError(RuntimeError):
    """超出每分鐘請求次數限制。"""


class SourceUnavailableError(RuntimeError):
    """教育平台無法存取（網路錯誤或 5xx）。"""

    def __init__(self, source_name: str, url: str, reason: str = "") -> None:
        self.source_name = source_name
        self.url = url
        super().__init__(f"{source_name} ({url}): {reason}")


class LoginRequiredError(RuntimeError):
    """資源需要登入才能存取（401/403）。"""


# ──────────────────────────────────────────
# Adapter Protocol
# ──────────────────────────────────────────

class DirectoryAdapter(Protocol):
    """可插拔目錄導航介面 — 負責發現教育平台。"""

    source_id: str
    access_strategy: AccessStrategy

    async def discover(self, request: DiscoveryRequest) -> list[EducationSource]: ...


class BrowseAdapter(Protocol):
    """可插拔平台瀏覽介面 — 負責在官方平台上搜尋資源。"""

    async def browse(
        self, source: EducationSource, request: BrowseRequest
    ) -> list[SearchResult]: ...

    async def read(self, url: str, extract: list[str]) -> dict[str, Any]: ...


class ExamArchiveAdapter(Protocol):
    """考古題來源介面 — 回傳試題下載連結與 metadata，不下載全文。"""

    async def search(self, request: ExamSearchRequest) -> list[ExamQuestionResult]: ...
