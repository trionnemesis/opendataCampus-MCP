# Source Reliability Corrections

## Overview
Correct source availability behavior without adding MCP tools, dependencies, or configuration. The existing `EDUMARKET_API_KEY` remains optional: when absent, the source returns a structured unavailable error; when present, current official-API behavior remains available. Runtime assembly becomes internal shared code only.

## Design Principles

1. **Explicit unavailable over broken fallback** — an optional official API may be unavailable, but must not issue a known-failing web request.
2. **One runtime assembly** — server, smoke, and E2E must receive the same registry and policies.
3. **Canonical source data** — catalog URL and query template must use the same verified host.
4. **No secret persistence** — the key remains runtime-only and is never printed, stored, or committed.

## Architecture

```
build_server() ─┐
smoke_sources ──┼──> build_runtime() ──> EdBrowserService
integration_e2e ┘          │
                             ├── WebSearchAdapter
                             ├── EduMarketApiAdapter
                             ├── OpenDataApiAdapter
                             ├── TwCampusDirectoryAdapter
                             └── CeecExamAdapter
```

### Option A: Keep three assembly paths

- Fewer immediate code moves.
- Smoke and E2E can diverge from production again after the next adapter change.

### Option B: Add an internal runtime factory

- One registry and one policy composition serve all three consumers.
- Requires a focused internal module and cleanup ownership.

**Recommendation: Option B** — three duplicate assembly paths already exist, and Issue #2 requires production-equivalent smoke validation.

## Configuration

`EDUMARKET_API_KEY` is optional. Precedence:

1. Process environment value read by the existing `EduMarketApiAdapter`.
2. Absent value: adapter returns `SourceUnavailableError` before any HTTP request.

No new configuration source is added. The callback is optional — when the key is absent, every non-EduMarket source works exactly as before.

## Implementation Plan

### Phase 1: Explicit no-key education-market behavior

**Files:** `mcp_server/server.py`, `tests/test_service.py`, `tests/test_server.py`, `docs/setup.md`, `docs/sources.md`.

#### 1a. Replace the old fallback expectation with source-unavailable routing tests (~30 lines)

Use the existing `SourceUnavailableError` behavior from `EduMarketApiAdapter`; assert an `OFFICIAL_API` adapter handles the education-market source and fallback web is never awaited.

#### 1b. Register the existing adapter regardless of key presence (~8 lines)

```python
adapters[AccessStrategy.OFFICIAL_API] = EduMarketApiAdapter(html_reader=web)
```

#### 1c. Update no-key documentation (~12 lines)

Document `source_unavailable` as an explicit configuration result, not a web-search downgrade.

**Tests for Phase 1:** (~45 lines)

- absent key causes no adapter HTTP request;
- service routes education-market to the official adapter;
- MCP tool returns `source_unavailable`;
- existing configured-key adapter tests remain green.

### Phase 2: Canonical CIRN host

**Files:** `repository/source_cache.py`, `adapters/web_search.py`, `tests/test_source_router.py`, `docs/sources.md`.

#### 2a. Add canonical-host assertions (~12 lines)

Assert both catalog URL and named search template use `https://cirn.k12ea.gov.tw`.

#### 2b. Replace the two stale hosts (~2 lines)

Update only `_CATALOG` and `SEARCH_TEMPLATES`.

#### 2c. Update source-health documentation (~8 lines)

Record that CIRN is expected to use the canonical verified host; live result remains an environment-time check.

**Tests for Phase 2:** (~12 lines)

- catalog and template host equality;
- existing source-router tests remain green;
- live smoke reports CIRN separately from any unrelated source failure.

### Phase 3: Shared runtime assembly

**Files:** `NEW — mcp_server/runtime.py`, `mcp_server/server.py`, `scripts/smoke_sources.py`, `scripts/integration_e2e.py`, `NEW — tests/test_runtime.py`.

#### 3a. Add Runtime ownership and factory (~70 lines)

```python
class AsyncCloseable(Protocol):
    async def aclose(self) -> None: ...

@dataclass
class Runtime:
    service: EdBrowserService
    adapters: dict[AccessStrategy, BrowseAdapter]
    closeables: tuple[AsyncCloseable, ...]

    async def aclose(self) -> None:
        for closeable in self.closeables:
            await closeable.aclose()

def build_runtime() -> Runtime:
    policy = BrowserPolicy()
    known_sources = get_known_sources()
    router = SourceRouter(known_sources)
    url_policy = PublicEducationUrlPolicy.from_sources(known_sources.values())
    twcampus = TwCampusDirectoryAdapter(policy)
    web = WebSearchAdapter(policy=policy, url_policy=url_policy)
    edumarket = EduMarketApiAdapter(html_reader=web)
    opendata = OpenDataApiAdapter()
    exam = CeecExamAdapter(policy)
    adapters = {
        AccessStrategy.WEB_SEARCH: web,
        AccessStrategy.OFFICIAL_API: edumarket,
        AccessStrategy.OPEN_DATA: opendata,
    }
    service = EdBrowserService(policy, router, twcampus, adapters, web, exam, url_policy)
    return Runtime(service, adapters, (twcampus, web, edumarket, opendata, exam))
```

#### 3b. Delegate all three entry points to the factory (~45 lines)

Server keeps its public `build_server()` API. Smoke and E2E use `try/finally` to close runtime resources.

#### 3c. Add composition and cleanup tests (~55 lines)

Assert the registry has WEB_SEARCH, OFFICIAL_API, and OPEN_DATA without a key; verify all closeables are called once.

**Tests for Phase 3:** (~55 lines)

- no-key and key-present registry invariants;
- runtime cleanup invariant;
- server and script source imports use `build_runtime`;
- full test suite and no-key smoke.

## Integration Issues & Edge Cases

1. A configured key is not validated by this repository run; it stays an explicit external acceptance step.
2. Smoke must classify no-key education-market as `UNAVAILABLE`, not silently treat it as an empty search.
3. Runtime cleanup must not change FastMCP's current lifecycle; `build_server()` retains its public return type.
4. CIRN response parsing may still return empty results if its HTML changes; canonical TLS reachability and parser accuracy are separate signals.

## Files Changed Summary

| File | Phase | Changes |
|---|---:|---|
| `mcp_server/runtime.py` | 3 | NEW — shared runtime factory and cleanup owner |
| `mcp_server/server.py` | 1, 3 | explicit EduMarket registration and factory use |
| `repository/source_cache.py` | 2 | CIRN canonical URL |
| `adapters/web_search.py` | 2 | CIRN search template |
| `scripts/smoke_sources.py` | 3 | shared runtime and cleanup |
| `scripts/integration_e2e.py` | 3 | shared runtime and cleanup |
| `tests/test_*.py` | 1–3 | behavior and composition coverage |
| `docs/setup.md`, `docs/sources.md` | 1–2 | accurate no-key and CIRN behavior |

**Total new code**: ~125 lines / **Total test code**: ~112 lines

## Rollout Plan

1. Commit Phase 1 as `fix(edumarket): report missing API key explicitly`; run targeted tests.
2. Commit Phase 2 as `fix(cirn): use canonical endpoint`; run targeted tests and live smoke.
3. Commit Phase 3 as `refactor(runtime): share adapter assembly`; run composition tests, full tests, and smoke.
4. Run an independent review because the accumulated diff crosses three files and 150 lines.
5. Push the existing feature branch after final verification.

Each phase is independently mergeable and testable.
