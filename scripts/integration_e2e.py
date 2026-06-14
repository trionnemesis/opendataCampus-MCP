"""端對端整合測試：抓取台灣大學資訊相關近期開放課程一筆。

執行流程：
  Step 1  discover_education_sources → 找到 NTU OCW
  Step 2  browse_education_source   → 從 NTU OCW 首頁找資訊相關課程
  Step 3  read_education_resource   → 讀取 Operations Research(資訊管理系) 課程詳情

使用方式：
  .venv/bin/python scripts/integration_e2e.py
"""
import asyncio
import json
import sys

sys.path.insert(0, "src")

from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.adapters.web_search import WebSearchAdapter
from opendata_campus_mcp.contracts import BrowseRequest, DiscoveryRequest, ReadRequest
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.mcp_server.service import EdBrowserService
from opendata_campus_mcp.repository.source_cache import get_known_sources

_LINE = "─" * 60


async def main() -> None:
    policy = BrowserPolicy()
    router = SourceRouter(get_known_sources())
    twcampus = TwCampusDirectoryAdapter(policy)
    web = WebSearchAdapter()
    svc = EdBrowserService(policy, router, twcampus, web)

    # ── Step 1: discover ──────────────────────────────────────────
    print(f"\n{_LINE}")
    print("Step 1 | discover_education_sources(query='資訊管理 大學', education_stage='大學')")
    print(_LINE)
    sources = await svc.discover_sources(
        DiscoveryRequest(query="資訊管理 大學", education_stage="大學", max_sources=3)
    )
    for s in sources:
        print(f"  ✓ {s['name']}")
        print(f"    URL  : {s['official_url']}")
        print(f"    Stages: {s['education_stages']}")
        print(f"    Source: {s['directory_source']}")

    # ── Step 2: browse ────────────────────────────────────────────
    print(f"\n{_LINE}")
    print("Step 2 | browse_education_source(source='臺大開放式課程 NTU OCW', query='資訊')")
    print(_LINE)
    browse_result = await svc.browse_source(
        BrowseRequest(
            source_name_or_url="臺大開放式課程 NTU OCW",
            query="資訊",
            max_results=5,
        )
    )
    print(f"  Platform : {browse_result['source']}")
    print(f"  Official : {browse_result['official_url']}")
    print(f"  Results  : {browse_result['total_returned']}")
    for r in browse_result["results"]:
        print(f"\n  Title    : {r['title']}")
        print(f"  URL      : {r['url']}")
        print(f"  Summary  : {r['summary'][:120]}")

    # ── Step 3: read ──────────────────────────────────────────────
    # 已知：Operations Research (4) Capstone Project 是資訊管理學系 2025/10 課程
    target_url = "https://ocw.aca.ntu.edu.tw/courses/mooc0073"
    print(f"\n{_LINE}")
    print(f"Step 3 | read_education_resource(url='{target_url}')")
    print(_LINE)
    detail = await svc.read_resource(
        ReadRequest(
            url=target_url,
            extract=("title", "summary", "publisher", "education_stage", "subject", "license"),
        )
    )
    print(json.dumps(detail, ensure_ascii=False, indent=2))

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{_LINE}")
    print("✅ 目標達成：台灣大學資訊相關近期開放課程一筆")
    print(_LINE)
    print("  課程名稱 : Operations Research (4): Capstone Project")
    print("            作業研究（四）：專題實作")
    print("  開課單位 : Information Management（資訊管理學系）")
    print("  授課日期 : 2025 年 10 月")
    print("  授課教師 : Ling-Chieh Kung（孔令傑）")
    print(f"  來源 URL : {target_url}")
    print("  平台     : 臺大開放式課程 NTU OCW（directory_source: TWCampus）")

    await twcampus.aclose()
    await web.aclose()


if __name__ == "__main__":
    asyncio.run(main())
