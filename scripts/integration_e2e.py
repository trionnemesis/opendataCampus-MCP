"""端對端整合測試：教育大市集官方 API（OFFICIAL_API adapter）。

需 EDUMARKET_API_KEY 環境變數（申請見 docs/setup.md）。未設時印提示並跳過（退出碼 0）。

執行流程：
  Step 1  discover_education_sources → 找到教育大市集（access_strategy=OFFICIAL_API）
  Step 2  browse_education_source   → 經官方 v2 API 搜尋,回結構化結果（含學制/領域）
  Step 3  read_education_resource   → 讀取單一資源頁摘要

使用方式：
  EDUMARKET_API_KEY=<key> .venv/bin/python scripts/integration_e2e.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "src")

from opendata_campus_mcp.adapters.edumarket import EduMarketApiAdapter
from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.adapters.web_search import WebSearchAdapter
from opendata_campus_mcp.contracts import (
    AccessStrategy,
    BrowseRequest,
    DiscoveryRequest,
    ReadRequest,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.mcp_server.service import EdBrowserService
from opendata_campus_mcp.repository.source_cache import get_known_sources

_LINE = "─" * 60


async def main() -> int:
    api_key = os.environ.get("EDUMARKET_API_KEY")
    if not api_key:
        print("⚠️  未設 EDUMARKET_API_KEY — 跳過教育大市集官方 API e2e。")
        print("    申請：登入 market.cloud.edu.tw → 會員中心 → 資料設定 → API應用服務")
        print("    執行：EDUMARKET_API_KEY=<key> .venv/bin/python scripts/integration_e2e.py")
        return 0

    policy = BrowserPolicy()
    router = SourceRouter(get_known_sources())
    twcampus = TwCampusDirectoryAdapter(policy)
    web = WebSearchAdapter()
    edumarket = EduMarketApiAdapter(api_key, html_reader=web)
    adapters = {
        AccessStrategy.WEB_SEARCH: web,
        AccessStrategy.OFFICIAL_API: edumarket,
    }
    svc = EdBrowserService(policy, router, twcampus, adapters, fallback=web)

    # ── Step 1: discover ──────────────────────────────────────────
    print(f"\n{_LINE}")
    print("Step 1 | discover_education_sources(query='教案 國中', education_stage='國中')")
    print(_LINE)
    sources = await svc.discover_sources(
        DiscoveryRequest(query="教案 國中", education_stage="國中", max_sources=3)
    )
    for s in sources:
        print(f"  ✓ {s['name']}  [{s['access_strategy']}]")
        print(f"    URL   : {s['official_url']}")

    # ── Step 2: browse（官方 API）─────────────────────────────────
    print(f"\n{_LINE}")
    print("Step 2 | browse_education_source(source='教育大市集', query='密度')")
    print(_LINE)
    browse_result = await svc.browse_source(
        BrowseRequest(source_name_or_url="教育大市集", query="密度", max_results=5)
    )
    print(f"  Platform : {browse_result['source']}")
    print(f"  Results  : {browse_result['total_returned']}")
    first_url = None
    for r in browse_result["results"]:
        first_url = first_url or r["url"]
        print(f"\n  Title    : {r['title']}")
        print(f"  URL      : {r['url']}")
        print(f"  Stage    : {r['education_stage']}")
        print(f"  Subject  : {r['subject']}")
        print(f"  Summary  : {r['summary'][:120]}")

    # ── Step 3: read ──────────────────────────────────────────────
    if first_url:
        print(f"\n{_LINE}")
        print(f"Step 3 | read_education_resource(url='{first_url}')")
        print(_LINE)
        detail = await svc.read_resource(
            ReadRequest(
                url=first_url,
                extract=("title", "summary", "publisher", "education_stage", "subject", "license"),
            )
        )
        print(json.dumps(detail, ensure_ascii=False, indent=2))

    await twcampus.aclose()
    await web.aclose()
    await edumarket.aclose()

    print(f"\n{_LINE}")
    print("✅ 教育大市集官方 API e2e 完成")
    print(_LINE)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
