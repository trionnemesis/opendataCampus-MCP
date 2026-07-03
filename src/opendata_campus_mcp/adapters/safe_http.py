"""Redirect-aware HTTP requests with URL and request-budget enforcement."""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

from opendata_campus_mcp.domain.browser_policy import BrowserPolicy
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    url_policy: PublicEducationUrlPolicy,
    browser_policy: BrowserPolicy,
) -> httpx.Response:
    """GET an allowed URL, validating every redirect before it is requested."""
    current_url = url
    pages_used = 0

    while True:
        url_policy.validate(current_url)
        browser_policy.check_page_limit(pages_used)
        host = urlparse(current_url).hostname or ""
        browser_policy.check_rate_limit(host.lower())
        response = await client.get(current_url, follow_redirects=False)
        pages_used += 1

        location = response.headers.get("Location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response
        current_url = urljoin(current_url, location)
