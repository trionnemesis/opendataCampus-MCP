"""FastMCP server — Education Resource Browser MCP（3 工具）。

工具設計對應 spec/features/：
  discover_education_sources → discover-sources.feature
  browse_education_source    → browse-source.feature
  read_education_resource    → read-resource.feature

瀏覽政策：每次請求最多 2 頁 TWCampus，每分鐘最多 3 次，不排程，不遞迴。
"""
from __future__ import annotations

import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from opendata_campus_mcp.adapters.ceec_exam import CeecExamAdapter
from opendata_campus_mcp.adapters.edumarket import EduMarketApiAdapter
from opendata_campus_mcp.adapters.opendata import OpenDataApiAdapter
from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.adapters.web_search import WebSearchAdapter
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseAdapter,
    BrowseRequest,
    DiscoveryRequest,
    ExamSearchRequest,
    LoginRequiredError,
    PolicyViolationError,
    RateLimitError,
    ReadRequest,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.mcp_server.service import EdBrowserService
from opendata_campus_mcp.repository.source_cache import get_known_sources

_INSTRUCTIONS = """\
教育資源導航 MCP — 以 TWCampus 作為目錄入口，路由至台灣官方教育平台搜尋。

查詢流程：
  1. discover_education_sources — 找到相關官方教育平台（從本地目錄 + TWCampus）
  2. browse_education_source    — 在指定平台上搜尋學習資源
  3. read_education_resource    — 讀取單一資源頁面的摘要資訊
  4. search_exam_questions      — 取得 CEEC 學測/分科測驗考古題的官方下載連結（不下載全文）

瀏覽政策（合規護欄）：
  - 每次請求最多 2 頁；每分鐘最多 3 次（per-domain 滑動視窗）
  - 不執行排程爬取；不遞迴導航；不儲存完整 HTML / 不下載試題 PDF 全文
  - 所有結果均包含來源標記
  - 不嘗試登入或繞過任何存取控制；考古題僅支援 CEEC 學測/分科,會考因 robots.txt 排除
  - 政府資料開放平臺提供結構化教育統計/名錄類開放資料（附 CSV/JSON 下載點），非學習教材
"""

_SUPPORTED_EXAM_TYPES = ("學測", "分科測驗")


def build_server() -> FastMCP:
    policy = BrowserPolicy()
    known_sources = get_known_sources()
    router = SourceRouter(known_sources)
    url_policy = PublicEducationUrlPolicy.from_sources(known_sources.values())
    twcampus = TwCampusDirectoryAdapter(policy)
    web = WebSearchAdapter(policy=policy, url_policy=url_policy)
    adapters: dict[AccessStrategy, BrowseAdapter] = {
        AccessStrategy.WEB_SEARCH: web,
        AccessStrategy.OPEN_DATA: OpenDataApiAdapter(),  # data.gov.tw,無 key,無條件註冊
    }
    # 有 EDUMARKET_API_KEY 才註冊教育大市集官方 API；否則該來源自然降級回 web_search
    api_key = os.environ.get("EDUMARKET_API_KEY")
    if api_key:
        adapters[AccessStrategy.OFFICIAL_API] = EduMarketApiAdapter(
            api_key, html_reader=web
        )
    exam = CeecExamAdapter(policy)  # 與 twcampus 共用同一 policy（per-domain 計數互不干擾）
    service = EdBrowserService(
        policy, router, twcampus, adapters, fallback=web, exam_adapter=exam,
        url_policy=url_policy,
    )

    mcp = FastMCP("opendata-campus-mcp", instructions=_INSTRUCTIONS)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # ── Tool 1：discover_education_sources ────────────────────────────────────

    @mcp.tool()
    async def discover_education_sources(
        query: str,
        education_stage: str | None = None,
        subject: str | None = None,
        max_sources: int = 3,
    ) -> list[dict]:
        """從 TWCampus 目錄找到相關官方教育平台（最多 max_sources 個）。

        education_stage 可為：國小 / 國中 / 高中 / 大學 / 技職 / 全階段
        回傳每個平台的 name、official_url、categories、directory_source。
        TWCampus 僅作路由目錄，不作為資源倉庫；本地目錄優先。
        """
        req = DiscoveryRequest(
            query=query,
            education_stage=education_stage,
            subject=subject,
            max_sources=min(max_sources, 5),
        )
        try:
            return await service.discover_sources(req)
        except RateLimitError as exc:
            return [{"error": "rate_limited", "message": str(exc)}]
        except PolicyViolationError as exc:
            return [{"error": "policy_violated", "message": str(exc)}]

    # ── Tool 2：browse_education_source ───────────────────────────────────────

    @mcp.tool()
    async def browse_education_source(
        source: str,
        query: str,
        max_results: int = 5,
    ) -> dict:
        """在指定官方教育平台上搜尋學習資源。

        source：平台名稱（如「教育大市集」）或官方 URL。
        回傳 results 列表，每筆含 title、url、summary、source_name、source_url。
        max_results 上限 5；不嘗試登入或繞過任何存取控制。
        """
        req = BrowseRequest(
            source_name_or_url=source,
            query=query,
            max_results=min(max_results, 5),
        )
        try:
            return await service.browse_source(req)
        except SourceUnavailableError as exc:
            return {
                "error": "source_unavailable",
                "source": exc.source_name,
                "url": exc.url,
                "message": str(exc),
            }
        except LoginRequiredError as exc:
            return {"error": "login_required", "message": str(exc)}
        except PolicyViolationError as exc:
            return {"error": "policy_violated", "message": str(exc)}
        except RateLimitError as exc:
            return {"error": "rate_limited", "message": str(exc)}

    # ── Tool 3：read_education_resource ───────────────────────────────────────

    @mcp.tool()
    async def read_education_resource(
        url: str,
        extract: list[str] | None = None,
    ) -> dict:
        """讀取單一公開教育資源頁面的關鍵資訊（摘要，不儲存全文）。

        extract 可指定欄位：title / summary / publisher / education_stage / subject / license
        回傳物件包含 url 來源欄位；summary 不超過 500 字元。
        不嘗試登入或繞過任何存取控制。
        """
        fields = extract or [
            "title", "summary", "publisher",
            "education_stage", "subject", "license",
        ]
        req = ReadRequest(url=url, extract=tuple(fields))
        try:
            return await service.read_resource(req)
        except LoginRequiredError as exc:
            return {"error": "login_required", "url": url, "message": str(exc)}
        except SourceUnavailableError as exc:
            return {"error": "source_unavailable", "url": url, "message": str(exc)}
        except PolicyViolationError as exc:
            return {"error": "policy_violated", "message": str(exc)}
        except RateLimitError as exc:
            return {"error": "rate_limited", "message": str(exc)}

    # ── Tool 4：search_exam_questions ─────────────────────────────────────────

    @mcp.tool()
    async def search_exam_questions(
        exam_type: str,
        year: str | None = None,
        subject: str | None = None,
        max_results: int = 10,
    ) -> dict:
        """搜尋台灣升學考古題，回傳官方試題檔案下載連結與結構化 metadata。

        exam_type：學測 / 分科測驗（第一階僅此二者；會考因 robots.txt 限制不納入）。
        year：民國年字串如「115」，省略則不限。
        subject：科目關鍵字如 國綜 / 英文 / 數學A，省略則不限。
        回傳 questions[]，每筆含 exam_type/year/subject/paper_type/title/download_url/source。
        年份與科目為 best-effort 解析（每筆附原始 title）；連結多為 PDF，部分另有 .docx。
        不下載或儲存試題內容。單次僅掃描最新約 20 筆，較舊年份請縮小 subject 或分次查詢。
        """
        if exam_type not in _SUPPORTED_EXAM_TYPES:
            return {
                "error": "unsupported_exam_type",
                "message": f"目前僅支援 {' / '.join(_SUPPORTED_EXAM_TYPES)}；"
                           "會考因 robots.txt Disallow 不納入",
                "exam_type": exam_type,
            }
        req = ExamSearchRequest(
            exam_type=exam_type,
            year=year,
            subject=subject,
            max_results=min(max_results, 20),
        )
        try:
            return await service.search_exam_questions(req)
        except RateLimitError as exc:
            return {"error": "rate_limited", "message": str(exc)}
        except PolicyViolationError as exc:
            return {"error": "policy_violated", "message": str(exc)}
        except SourceUnavailableError as exc:
            return {
                "error": "source_unavailable",
                "source": exc.source_name,
                "url": exc.url,
                "message": str(exc),
            }
        except LoginRequiredError as exc:
            return {"error": "login_required", "message": str(exc)}

    return mcp
