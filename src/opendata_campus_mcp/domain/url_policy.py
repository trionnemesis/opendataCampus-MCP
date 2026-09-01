"""Catalog-backed policy for outbound education-resource URLs."""
from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

from opendata_campus_mcp.contracts import EducationSource, PolicyViolationError


class PublicEducationUrlPolicy:
    """Allow HTTPS URLs owned by a known education-source host."""

    def __init__(self, allowed_hosts: Iterable[str]) -> None:
        self._allowed_hosts = frozenset(
            _catalog_domain(host) for host in allowed_hosts if host
        )

    @classmethod
    def from_sources(
        cls, sources: Iterable[EducationSource]
    ) -> PublicEducationUrlPolicy:
        hosts = [urlparse(source.official_url).hostname or "" for source in sources]
        return cls(hosts)

    def validate(self, url: str) -> str:
        """Return *url* when allowed; otherwise raise without echoing secrets."""
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            parsed.port
        except ValueError as exc:
            raise PolicyViolationError("outbound URL is invalid") from exc

        if parsed.scheme.lower() != "https" or not host:
            raise PolicyViolationError("outbound URL must use HTTPS with a valid host")
        if parsed.username is not None or parsed.password is not None:
            raise PolicyViolationError("outbound URL credentials are not allowed")
        if host == "localhost" or host.endswith(".localhost"):
            raise PolicyViolationError("outbound URL host is not allowed")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise PolicyViolationError("outbound URL IP literals are not allowed")

        if not any(
            host == allowed or host.endswith(f".{allowed}")
            for allowed in self._allowed_hosts
        ):
            raise PolicyViolationError("outbound URL host is not in the source catalog")
        return url


def _catalog_domain(host: str) -> str:
    normalized = host.lower().rstrip(".")
    return normalized.removeprefix("www.")


# 只有這兩個 scheme 可以安全地交給 MCP client 當連結呈現或再讀取。
# javascript: / data: / vbscript: / file: 進到會渲染結果的 client 就是
# 一個可點擊的執行點(CWE-79),而 urljoin() 對未知 scheme 是原樣回傳,
# 不會替我們擋掉。
_SAFE_RESULT_SCHEMES = frozenset({"http", "https"})


def safe_result_url(href: str, base: str) -> str | None:
    """把抓回來的 href 解析成可安全回傳的絕對 URL;不安全則回 None。

    href 來自遠端 HTML / 第三方 JSON,屬不可信輸入。此函式只做兩件事:
    以 base 解析相對路徑、確認結果 scheme 在白名單內 —— 不做主機白名單
    (那是 PublicEducationUrlPolicy 的職責,套用在「我們要外連」的時候;
    這裡處理的是「我們要回傳給 client」的連結)。
    """
    if not href:
        return None
    try:
        resolved = urljoin(base, href.strip())
        scheme = (urlparse(resolved).scheme or "").lower()
    except ValueError:
        return None
    return resolved if scheme in _SAFE_RESULT_SCHEMES else None
