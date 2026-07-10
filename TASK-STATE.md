# TASK-STATE — Source reliability corrections
更新: 2026-07-11T00:00:00+08:00 / 進度: 7/7 milestones

## Goal
使用者要求：依既有討論執行修正，先完成並 commit spec，再確認實作範圍，實作、驗證、commit、push。
成功判準：EduMarket 無 key 不發生 HTTP fallback、CIRN 使用可驗證 host、server/smoke/E2E 共用 runtime assembly、所有指定驗證通過且 branch 已 push。

## Constraints
- 僅實作 source-reliability unit；HTTP body cap、全 adapter gateway、audit events、deployment lock decision 不在本輪。
- 不讀取、輸出或寫入 `EDUMARKET_API_KEY`。
- 每個 bugfix 與 runtime wiring 使用獨立 commit；不新增 dependency、MCP tool 或 config。

## Completed
- 1. L2 + L5 routing and current state inspection. Evidence: `git status --short --branch` clean; branch tracks `origin/feat/edumarket-official-api`.
- 2. Premise verification. Evidence: `git log -p -S 'EDUMARKET_API_KEY'` identifies intentional fallback in `d5cbfeb`; live probes show market fallback HTTP 404, old CIRN TLS failure, canonical CIRN HTTP 200.
- 3. Wrote source-reliability spec and L2 plan. Evidence: `docs/superpowers/specs/2026-07-11-source-reliability-design.md`, `.plans/source-reliability.md`, and updated BDD features.
- 4. Committed the spec-only change. Evidence: `git show --stat --oneline d62407f` → 5 files, 276 insertions.
- 5. Completed EduMarket no-key RED→GREEN. Evidence: targeted pytest command → 13 passed; the server now routes market to OFFICIAL_API and returns structured unavailable without web fallback.
- 6. Completed CIRN canonical-host RED→GREEN. Evidence: source-router/web-search tests → 20 passed; live smoke changed CIRN from TLS failure to `EMPTY` while the old smoke registry still reports EduMarket HTTP 404.
- 7. Completed shared runtime RED→GREEN. Evidence: runtime/server tests → 6 passed; full suite → 108 passed; no-key smoke uses OFFICIAL_API and returns `EDUMARKET_API_KEY not configured` before HTTP.

## Active State
- cwd: `/Users/warden/opendateCampus_MCP`
- branch: `feat/edumarket-official-api`
- current implementation changes: Phase 3 shared runtime, test coverage, and source-health/architecture documentation; review passed, awaiting isolated commit and push
- last full validation: `.venv/bin/pytest tests/ -q` → 108 passed (before review follow-up test hardening)
- running processes: none

## Next Step
Run final verification, commit Phase 3, then push all three implementation commits.

## Blocked
- Configured-key live E2E remains blocked until the user provides `EDUMARKET_API_KEY` through the runtime environment. It does not block no-key behavior or mocked validation.

## Key Decisions
- Scope only EduMarket no-key handling, CIRN canonical host, and shared runtime wiring because they form one independently testable source-reliability unit.
- Select a shared runtime factory over duplicate script assembly because three current entry points assemble adapters independently.

## Relevant Files
- `src/opendata_campus_mcp/mcp_server/runtime.py:build_runtime` — production adapter registry and owned HTTP-client cleanup.
- `src/opendata_campus_mcp/mcp_server/server.py:build_server` — FastMCP tools use the shared runtime and close it in lifespan shutdown.
- `scripts/smoke_sources.py:main` / `scripts/integration_e2e.py:main` — consume the shared runtime factory.
- `src/opendata_campus_mcp/repository/source_cache.py:_CATALOG` — CIRN canonical URL.
- `src/opendata_campus_mcp/adapters/web_search.py:SEARCH_TEMPLATES` — CIRN search URL.

## Historical（STALE — 除非使用者重新要求，禁止主動執行）
- HTTP gateway/body cap/content-type enforcement is deferred to Issue #2 follow-up.
- Audit events and dependency lock strategy are not part of this implementation unit.
