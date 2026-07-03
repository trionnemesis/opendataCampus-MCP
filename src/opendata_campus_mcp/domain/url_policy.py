"""Catalog-backed policy for outbound education-resource URLs."""
from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlparse

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
