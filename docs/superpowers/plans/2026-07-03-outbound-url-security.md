# Outbound URL Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent arbitrary outbound fetches and enforce existing browser policy for generic browse/read traffic.

**Architecture:** Add a catalog-backed domain URL policy, validate redirects before following them, reject unresolved sources at the service boundary, and inject the policies into `WebSearchAdapter`. Preserve current DTOs and adapter routing.

**Tech Stack:** Python 3.11, httpx, pytest, pytest-asyncio, FastMCP.

---

### Task 1: URL policy

**Files:**
- Create: `src/opendata_campus_mcp/domain/url_policy.py`
- Create: `tests/test_url_policy.py`

- [ ] Write tests for allowed canonical/subdomain HTTPS URLs and rejected scheme, credentials, localhost, IP literal, malformed, and unknown-host URLs.
- [ ] Run `.venv/bin/pytest tests/test_url_policy.py -q` and confirm failure because `url_policy` does not exist.
- [ ] Implement `PublicEducationUrlPolicy.from_sources()` and `validate(url) -> str`, raising `PolicyViolationError` for rejected URLs.
- [ ] Run `.venv/bin/pytest tests/test_url_policy.py -q` and confirm all tests pass.

### Task 2: Service boundary

**Files:**
- Modify: `src/opendata_campus_mcp/mcp_server/service.py`
- Modify: `src/opendata_campus_mcp/mcp_server/server.py`
- Modify: `tests/test_service.py`

- [ ] Replace permissive unknown-source expectations with tests asserting `PolicyViolationError` and zero adapter calls.
- [ ] Add unknown-host read rejection and known-host read preservation tests.
- [ ] Run the focused tests and confirm they fail against the permissive implementation.
- [ ] Inject `PublicEducationUrlPolicy`; reject unresolved browse sources and read hosts before dispatch.
- [ ] Add `PolicyViolationError` handling to browse/read MCP tools.
- [ ] Run focused service tests and confirm they pass.

### Task 3: Redirect and request policy

**Files:**
- Create: `src/opendata_campus_mcp/adapters/safe_http.py`
- Modify: `src/opendata_campus_mcp/adapters/web_search.py`
- Modify: `tests/test_web_search.py`

- [ ] Add a redirect-to-unknown-host test that asserts no second request occurs.
- [ ] Add same-host redirect and fourth-request rate-limit tests.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement manual redirect handling with `follow_redirects=False`, five-hop maximum, URL validation before every GET, and per-request BrowserPolicy checks.
- [ ] Run focused tests and confirm they pass.

### Task 4: Documentation and full verification

**Files:**
- Modify: `docs/compliance.md`
- Modify: `docs/tools.md`
- Modify: `security_best_practices_report.md`

- [ ] Document the now-enforced known-host boundary and structured policy errors.
- [ ] Mark only the implemented findings as remediated; retain body-size, content-type, logging, source-health, and operational work as remaining risk.
- [ ] Run `.venv/bin/pytest tests/ -q` and expect zero failures.
- [ ] Run `.venv/bin/python -m compileall -q src tests scripts` and expect exit 0.
- [ ] Run `git diff --check` and expect exit 0.
- [ ] Commit the implementation, create a GitHub issue for the explicitly deferred phases, and push `feat/edumarket-official-api`.
