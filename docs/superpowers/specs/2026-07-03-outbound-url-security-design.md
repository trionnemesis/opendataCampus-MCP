# Outbound URL Security Design

## Goal

Close the MCP server's arbitrary outbound-fetch boundary without changing the public tool names or successful known-source behavior.

## Scope

This increment covers the first roadmap phase only:

- accept outbound URLs only when they use HTTPS and belong to the maintained education-source catalog;
- reject unknown `browse_education_source` values instead of constructing an ad hoc source;
- reject `read_education_resource` URLs whose host is not owned by a known source;
- reject URL credentials, IP literals, localhost, malformed hosts, and non-HTTPS schemes before network access;
- disable automatic redirects and validate every redirect target before following it;
- enforce `BrowserPolicy` for generic browse and read requests;
- add deterministic security-negative and legitimate-behavior tests.

Education-market fallback repair, CIRN endpoint repair, production-parity smoke wiring, body-size limits, content-type limits, and audit events remain separate follow-up work. They must be tracked in a GitHub issue after this increment is pushed.

## Architecture

Add `PublicEducationUrlPolicy` under `domain/`. It owns URL normalization and host authorization. Its allowlist is constructed from the canonical hosts in `source_cache`; subdomains are accepted only when they belong to an allowlisted parent domain. The policy has no network or adapter dependencies.

Add a small redirect-aware request helper under `adapters/`. It validates the initial URL, performs one HTTP request with `follow_redirects=False`, resolves each `Location` value, and validates it before the next request. Redirects consume the existing two-page `BrowserPolicy` budget, so no tool call can fetch a third page.

`EdBrowserService` remains the external security boundary. Unknown browse sources and unknown read hosts raise `PolicyViolationError`. `WebSearchAdapter` receives the URL policy and shared `BrowserPolicy`, then applies both before outbound browse/read requests.

## Data Flow

1. MCP tool parses the request into the existing contract.
2. Service resolves the source through `SourceRouter`.
3. Unknown source or unknown read host fails with `PolicyViolationError` before adapter dispatch.
4. `WebSearchAdapter` checks the per-domain request budget.
5. Redirect-aware HTTP helper validates the URL before each GET.
6. Existing response parsing and structured result behavior continues unchanged.

## Error Handling

- Unsafe URL or unknown source: `PolicyViolationError` and MCP `policy_violated` response.
- Per-domain rate limit: existing `RateLimitError` and MCP `rate_limited` response.
- Redirect chain requiring a third page: existing `PolicyViolationError`.
- HTTP transport, login-required, and source-unavailable behavior remains unchanged.

No external error may include URL userinfo, query parameters, or fragments from a rejected URL.

## Testing

Unit tests must prove rejection before the mocked adapter/client is called for:

- `http://` URLs;
- `localhost` and subdomains of localhost;
- IPv4 and IPv6 literals;
- URLs containing userinfo;
- unknown public hosts;
- redirects from an allowed host to an unknown host.

Positive tests must preserve known source browse/read, allowed same-domain redirects, and existing adapter routing. A rate-limit integration test must prove the fourth generic web request to one domain is rejected.

## Acceptance Criteria

- The source-to-sink path from arbitrary MCP input to `httpx.AsyncClient.get` is closed.
- Every redirect target is authorized before it is fetched.
- Generic browse/read requests consume the documented `BrowserPolicy` per-domain budget.
- Existing known-source tests and the full offline test suite pass.
- No dependency or lockfile changes are introduced.
