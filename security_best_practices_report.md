# Security and Data Retrieval Review

## Executive Summary

This review focused on the MCP server security boundary and live data retrieval behavior. The project has a clear intent: route users to official public education resources, avoid bulk crawling, and return short summaries only. The implementation currently has strong structure, but the outbound-fetch boundary is too permissive for an MCP tool.

Highest priority: block arbitrary outbound URL fetches, apply the same rate/page policy to all HTTP reads, validate redirects and final hosts, and add tests that make these guarantees executable.

Evidence boundary: repository-local review only. No live website probing was performed. The installed security guidance has Python web framework references for Flask/FastAPI/Django, but no FastMCP/MCP-specific or Python general backend reference, so findings below use repo evidence plus common Python/httpx/MCP security practice.

## Findings

### SEC-1 High: `browse` and `read` allow arbitrary outbound URL fetches

Impact: a model or caller can turn the MCP server into a server-side request primitive against non-education, internal, localhost, metadata, or otherwise unintended hosts.

Evidence:
- `src/opendata_campus_mcp/mcp_server/service.py:72-87` creates an ad hoc `EducationSource` when `source_name_or_url` is not found in the known catalog.
- `src/opendata_campus_mcp/mcp_server/service.py:110-111` passes `ReadRequest.url` directly to `WebSearchAdapter.read`.
- `src/opendata_campus_mcp/adapters/web_search.py:85-98` performs `httpx.AsyncClient.get(url)` for the supplied URL and parses the response.
- `tests/test_service.py:151-155` explicitly locks in the behavior that an unknown URL source is accepted.

Recommendation:
- Add a central `PublicEducationUrlPolicy` before every outbound GET.
- Allow only `https` URLs by default; reject userinfo, IP literals unless explicitly allowlisted, localhost, loopback, private, link-local, multicast, reserved, and cloud metadata ranges.
- DNS-resolve hostnames and reject results that resolve to private/reserved networks.
- Restrict `read_education_resource` to known source domains or URLs returned by a prior trusted `browse` result.
- Change the unknown-source path to reject by default, or gate dynamic sources through TWCampus discovery plus validation.

### SEC-2 High: `BrowserPolicy` is not enforced for `browse` and `read`

Impact: the documented per-domain request limit can be bypassed through repeated `browse_education_source` or `read_education_resource` calls.

Evidence:
- `README.md:278-291` documents per-domain request limits and other browsing guardrails.
- `src/opendata_campus_mcp/domain/browser_policy.py:29-47` implements rate and page-limit checks.
- `src/opendata_campus_mcp/adapters/twcampus.py:51-52` applies the policy only to TWCampus discovery.
- `src/opendata_campus_mcp/mcp_server/service.py:88` and `src/opendata_campus_mcp/mcp_server/service.py:111` route browse/read directly to the web adapter without policy checks.
- `src/opendata_campus_mcp/adapters/web_search.py:68-69` and `src/opendata_campus_mcp/adapters/web_search.py:87-88` issue GET requests without calling `BrowserPolicy`.

Recommendation:
- Inject `BrowserPolicy` into `WebSearchAdapter` or wrap all outbound GETs in a single HTTP gateway.
- Enforce per-domain rate limits and page counts on `discover`, `browse`, and `read`.
- Return structured `rate_limited` / `policy_violated` errors consistently for all three MCP tools.

### SEC-3 Medium: redirects and parsed links can escape the intended source boundary

Impact: a trusted-looking education source or search result can lead the tool to non-education or internal targets through redirects or off-domain links.

Evidence:
- `src/opendata_campus_mcp/adapters/web_search.py:55-60` enables `follow_redirects=True`.
- `src/opendata_campus_mcp/adapters/twcampus.py:40-44` also enables redirects while discovering sources.
- `src/opendata_campus_mcp/adapters/web_search.py:131-137` resolves relative links but does not enforce same-host or known-host constraints.
- `src/opendata_campus_mcp/adapters/twcampus.py:72-81` accepts any external `http*` link from TWCampus except links containing `twcampus.org`.

Recommendation:
- Validate the original URL and every redirect target.
- Re-check final response URLs after redirects.
- Filter browse results to same registrable domain or a validated education-domain allowlist.
- Represent off-domain links explicitly instead of treating them as same-source resources.

### SEC-4 Medium: response body size and content type are not bounded before parsing

Impact: a caller can cause the server to download and parse unexpectedly large or non-HTML responses, creating memory/latency risk even though returned summaries are capped.

Evidence:
- `src/opendata_campus_mcp/adapters/web_search.py:82` parses `resp.text` for browse.
- `src/opendata_campus_mcp/adapters/web_search.py:97-98` parses the full response body before extracting requested fields.
- `src/opendata_campus_mcp/adapters/web_search.py:222-240` truncates the summary after parsing, not before download or parsing.

Recommendation:
- Stream responses with a maximum byte budget.
- Reject non-HTML/non-text content types for these tools.
- Add timeout, connection, and read-size limits in one shared HTTP gateway.
- Keep the returned summary cap, but enforce a separate fetched-body cap.

### SEC-5 Medium: raw URLs and transport errors can leak sensitive request details

Impact: user-supplied URLs containing query tokens, credentials, or internal hostnames can be echoed into logs or MCP-visible error messages.

Evidence:
- `src/opendata_campus_mcp/adapters/web_search.py:66` logs the full browse URL.
- `src/opendata_campus_mcp/adapters/web_search.py:86` logs the full read URL.
- `src/opendata_campus_mcp/contracts.py:112-115` includes the raw URL and reason in `SourceUnavailableError`.
- `src/opendata_campus_mcp/mcp_server/server.py:111-116` and `src/opendata_campus_mcp/mcp_server/server.py:141-143` return those details to the caller.

Recommendation:
- Sanitize URLs in logs and external errors: strip userinfo, query, and fragment.
- Keep full diagnostics only in protected debug traces if needed.
- Return stable error codes plus sanitized host/path context.

### DATA-1 Medium: source catalog and documentation are inconsistent

Impact: maintainers may troubleshoot the wrong domains, and data retrieval health claims can drift from the actual code path.

Evidence:
- `README.md:299-310` lists some official URLs that differ from `source_cache.py`.
- `src/opendata_campus_mcp/repository/source_cache.py:37-44` uses `https://cloud.edu.tw` for the education cloud entry.
- `src/opendata_campus_mcp/repository/source_cache.py:85-92` uses `https://www.naer.edu.tw` for the NAER entry.
- `README.md:347-364` documents live health findings for domains that are not necessarily the current implementation targets.

Recommendation:
- Treat source health as generated data, not hand-maintained prose.
- Add `last_verified_at`, `last_status`, and `verified_url` metadata for every source.
- Regenerate README health tables from `scripts/smoke_sources.py` output or move them to dated reports.

### DATA-2 Medium: tests do not cover security-negative URL cases

Impact: the riskiest retrieval behaviors can regress silently because current tests assert the permissive path.

Evidence:
- `tests/test_service.py:151-155` asserts that an unknown HTTPS URL becomes an ad hoc source.
- `tests/test_service.py:168-181` tests successful read and login-required propagation, but not invalid/private URLs.
- `tests/test_browser_policy.py:12-49` tests `BrowserPolicy` directly, but not whether browse/read apply it.

Recommendation:
- Add tests for `localhost`, `127.0.0.1`, `::1`, RFC1918 private ranges, link-local, metadata IPs, non-HTTPS schemes, userinfo URLs, oversized bodies, non-HTML responses, and redirect-to-private-host.
- Use `httpx.MockTransport` to avoid live network dependency.
- Update the existing unknown-source test to match the chosen security policy.

## Next-Stage Fix Plan

### Phase 1: Security Boundary

1. Add `domain/url_policy.py` or equivalent with URL normalization and validation.
2. Reject unknown direct sources by default in `EdBrowserService.browse_source`.
3. Restrict `read_resource` to known/validated public education hosts.
4. Apply `BrowserPolicy` to every outbound `browse` and `read` request.
5. Validate redirect chains and final URLs.
6. Add security-negative tests before changing behavior.

### Phase 2: Data Retrieval Correctness

1. Introduce source health metadata: `last_verified_at`, status, canonical URL, and known limitations.
2. Convert `scripts/smoke_sources.py` output into a dated artifact rather than static README claims.
3. Filter browse results to source-owned or allowlisted domains.
4. Add platform-specific parsers only where generic parsing is proven inaccurate.
5. Add response-size and content-type limits.

### Phase 3: Operational Hardening

1. Centralize outbound HTTP in one gateway with sanitized logs, timeouts, body caps, rate limits, and redirect validation.
2. Add lightweight audit events for `discover`, `browse`, `read`: sanitized host, status, result count, and policy decision.
3. Keep `HeadlessAdapter` disabled by default; if enabled later, require the same URL policy and per-domain limits.
4. Decide whether the project needs dependency pinning or a lock strategy for reproducible MCP deployments.

## Suggested First PR

Scope: URL policy plus tests only.

Acceptance criteria:
- Direct `read_education_resource("http://localhost:...")` is rejected before any network call.
- Direct `read_education_resource("https://127.0.0.1/...")` is rejected before any network call.
- Redirect from an allowed public host to a private host is rejected.
- Unknown `browse_education_source(source="https://unknown.example")` no longer creates an ad hoc source unless explicitly enabled by a validated source-discovery path.
- Existing known-source browse/read tests continue to pass with mocked HTTP.
