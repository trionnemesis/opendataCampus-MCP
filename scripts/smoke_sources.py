"""Live smoke test — 對全部 10 個內建教育來源各跑一次 browse，回報可達性與抓取健康度。

定位：維護者用的「live 診斷工具」，非 CI gate。實際連線台灣教育平台，
結果可能因各站結構改版、WAF、網路波動而異；用來快速看出哪些來源的
搜尋/解析器仍正常運作、哪些需要調整 SEARCH_TEMPLATES 或解析邏輯。

狀態分類：
  ✅ OK          連線成功且 browse 回傳 ≥1 筆結果
  ⚠️ EMPTY       連線成功但 0 筆（解析器未匹配該站結構，或關鍵字無命中）
  🔒 LOGIN       需登入（401/403）
  ❌ UNAVAILABLE 連線失敗 / 4xx / 5xx（SourceUnavailableError）
  💥 ERROR       其他未預期例外

退出碼：出現任何 UNAVAILABLE / ERROR（連線層級或程式失敗）→ 1，否則 0。
EMPTY 與 LOGIN 視為站點特性警告，不影響退出碼。

使用方式：
  .venv/bin/python scripts/smoke_sources.py
"""
import asyncio
import sys

sys.path.insert(0, "src")

from opendata_campus_mcp.adapters.twcampus import TwCampusDirectoryAdapter
from opendata_campus_mcp.adapters.web_search import WebSearchAdapter
from opendata_campus_mcp.contracts import (
    BrowseRequest,
    LoginRequiredError,
    SourceUnavailableError,
)
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.source_router import SourceRouter
from opendata_campus_mcp.mcp_server.service import EdBrowserService
from opendata_campus_mcp.repository.source_cache import get_known_sources

# 每個來源給一個該平台應有結果的代表性關鍵字
SMOKE_QUERIES: dict[str, str] = {
    "教育大市集": "數學",
    "因材網": "數學",
    "CIRN": "數學",
    "教育部數位教學資源入口網": "數學",
    "全民英檢 GEPT": "初級",
    "國立公共資訊圖書館": "閱讀",
    "教育部學力認證": "學測",
    "均一教育平台": "數學",
    "臺大開放式課程 NTU OCW": "資訊",
    "國教院課程資源網": "素養",
}

_DEFAULT_QUERY = "學習"
_LINE = "─" * 72
_ICON = {"OK": "✅", "EMPTY": "⚠️", "LOGIN": "🔒", "UNAVAILABLE": "❌", "ERROR": "💥"}


async def _probe(svc: EdBrowserService, name: str, query: str) -> tuple[str, str]:
    try:
        res = await svc.browse_source(
            BrowseRequest(source_name_or_url=name, query=query, max_results=5)
        )
        n = res.get("total_returned", 0)
        if n > 0:
            sample = res["results"][0]["title"][:48]
            return "OK", f"{n} 筆，例：{sample}"
        return "EMPTY", "連線成功但 0 筆（解析器未匹配或關鍵字無命中）"
    except LoginRequiredError as exc:
        return "LOGIN", str(exc)
    except SourceUnavailableError as exc:
        return "UNAVAILABLE", str(exc)
    except Exception as exc:  # noqa: BLE001
        return "ERROR", f"{type(exc).__name__}: {exc}"


async def main() -> int:
    policy = BrowserPolicy()
    router = SourceRouter(get_known_sources())
    twcampus = TwCampusDirectoryAdapter(policy)
    web = WebSearchAdapter()
    svc = EdBrowserService(policy, router, twcampus, web)

    sources = get_known_sources()
    print(f"Live smoke test — {len(sources)} 個內建教育來源")
    print(_LINE)

    rows: list[tuple[str, str]] = []
    for name in sources:
        query = SMOKE_QUERIES.get(name, _DEFAULT_QUERY)
        status, detail = await _probe(svc, name, query)
        icon = _ICON.get(status, "💥")
        print(f"{icon} {status:<11} {name}  (q='{query}')")
        print(f"     {detail}")
        rows.append((status, name))
        await asyncio.sleep(0.5)  # 對各站禮貌延遲

    await twcampus.aclose()
    await web.aclose()

    ok = sum(1 for s, _ in rows if s == "OK")
    empty = sum(1 for s, _ in rows if s == "EMPTY")
    login = sum(1 for s, _ in rows if s == "LOGIN")
    hard_fail = [n for s, n in rows if s in ("UNAVAILABLE", "ERROR")]

    print(_LINE)
    print(f"OK={ok}  EMPTY={empty}  LOGIN={login}  FAIL={len(hard_fail)} / {len(rows)}")
    if hard_fail:
        print("連線/程式失敗來源：" + ", ".join(hard_fail))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
