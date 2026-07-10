# Source Reliability Design

## Goal

Correct the three source-reliability defects identified in GitHub Issue #2 without expanding the MCP surface: education-market must fail explicitly when its API key is absent, CIRN must use its verified canonical host, and every executable entry point must assemble the same adapters.

## Scope

Included:

- register `EduMarketApiAdapter` whether or not `EDUMARKET_API_KEY` is set, relying on its existing no-key guard to return `SourceUnavailableError` before a request;
- replace `cirn.moe.edu.tw` with `cirn.k12ea.gov.tw` in the source catalog and search template;
- add one internal runtime factory shared by `build_server`, `scripts/smoke_sources.py`, and `scripts/integration_e2e.py`;
- close runtime-owned HTTP clients from CLI scripts;
- update affected tests and source documentation.

Excluded:

- full HTTP gateway adoption, response body caps, content-type limits, URL/error sanitization, result-domain filtering, audit events, and deployment dependency policy;
- configured-key live E2E, because the key must be user-provided at runtime and must not enter source control, logs, or this document.

## Verified Premises

- The current key-gated registration was intentionally introduced in `d5cbfeb`, but the fallback endpoint now returns HTTP 404.
- `https://cirn.moe.edu.tw/...` fails TLS hostname verification; `https://cirn.k12ea.gov.tw/...` responds HTTP 200.
- Server, smoke, and E2E currently construct adapter registries separately, so smoke cannot prove production configuration.

## Design

`mcp_server/runtime.py` will expose `build_runtime() -> Runtime`. `Runtime` owns the `EdBrowserService`, adapter registry, and the adapters that need `aclose()`. The factory always includes `OFFICIAL_API: EduMarketApiAdapter(html_reader=web)`. The existing adapter reads `EDUMARKET_API_KEY` only at runtime and raises `SourceUnavailableError` before building its API request when it is absent.

`build_server()` only obtains `runtime.service`; CLI scripts obtain the same runtime and call `await runtime.aclose()` in `finally`. The public MCP tools, contracts, environment variable name, and successful configured-key behavior remain unchanged.

## Acceptance Criteria

- No-key education-market browse returns `source_unavailable` and the fallback web adapter is not called.
- CIRN source and search template use `cirn.k12ea.gov.tw`.
- `build_server`, smoke, and E2E call the same runtime factory.
- The runtime registry includes WEB_SEARCH, OFFICIAL_API, and OPEN_DATA independently of whether a key exists.
- Targeted tests, full test suite, compileall, diff-check, and a no-key live smoke pass.
