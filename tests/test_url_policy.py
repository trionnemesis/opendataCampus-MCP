import pytest

from opendata_campus_mcp.contracts import PolicyViolationError
from opendata_campus_mcp.domain.url_policy import PublicEducationUrlPolicy
from opendata_campus_mcp.repository.source_cache import get_known_sources


@pytest.fixture
def policy() -> PublicEducationUrlPolicy:
    return PublicEducationUrlPolicy.from_sources(get_known_sources().values())


@pytest.mark.parametrize(
    "url",
    [
        "https://market.cloud.edu.tw/resource/1",
        "https://subdomain.naer.edu.tw/path?q=1#section",
    ],
)
def test_allows_known_https_hosts_and_subdomains(
    policy: PublicEducationUrlPolicy, url: str
) -> None:
    assert policy.validate(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://market.cloud.edu.tw/resource/1",
        "https://user:password@market.cloud.edu.tw/resource/1",
        "https://localhost/resource/1",
        "https://api.localhost/resource/1",
        "https://127.0.0.1/resource/1",
        "https://[::1]/resource/1",
        "https://unknown.example/resource/1",
        "not-a-url",
    ],
)
def test_rejects_unsafe_or_unknown_urls(
    policy: PublicEducationUrlPolicy, url: str
) -> None:
    with pytest.raises(PolicyViolationError):
        policy.validate(url)


def test_rejected_error_does_not_echo_sensitive_url(
    policy: PublicEducationUrlPolicy,
) -> None:
    url = "https://user:secret@unknown.example/path?token=secret#fragment"

    with pytest.raises(PolicyViolationError) as exc_info:
        policy.validate(url)

    message = str(exc_info.value)
    assert "secret" not in message
    assert "token" not in message
