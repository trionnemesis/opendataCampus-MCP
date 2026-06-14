"""對應 spec/features/browser-policy.feature。"""
from __future__ import annotations

import time

import pytest

from opendata_campus_mcp.contracts import PolicyViolationError, RateLimitError
from opendata_campus_mcp.domain.browser_policy import BrowserPolicy


def test_three_requests_within_limit():
    policy = BrowserPolicy()
    for _ in range(3):
        policy.check_rate_limit("twcampus.org")  # 不應拋出


def test_fourth_request_rate_limited():
    policy = BrowserPolicy()
    for _ in range(3):
        policy.check_rate_limit("twcampus.org")
    with pytest.raises(RateLimitError, match="rate limit exceeded"):
        policy.check_rate_limit("twcampus.org")


def test_different_domains_are_independent():
    policy = BrowserPolicy()
    for _ in range(3):
        policy.check_rate_limit("twcampus.org")
    # 不同網域不受影響
    policy.check_rate_limit("market.cloud.edu.tw")  # 不應拋出


def test_page_limit_within_boundary():
    policy = BrowserPolicy()
    policy.check_page_limit(pages_used=0)
    policy.check_page_limit(pages_used=1)


def test_page_limit_exceeded_at_boundary():
    policy = BrowserPolicy()
    with pytest.raises(PolicyViolationError, match="max_pages_per_request"):
        policy.check_page_limit(pages_used=2)  # max=2，=2 已超出


def test_page_limit_exceeded_beyond_boundary():
    policy = BrowserPolicy()
    with pytest.raises(PolicyViolationError):
        policy.check_page_limit(pages_used=5)


def test_scheduled_crawling_disabled_by_default():
    policy = BrowserPolicy()
    assert policy.scheduled_crawling is False


def test_recursive_navigation_disabled_by_default():
    policy = BrowserPolicy()
    assert policy.recursive_navigation is False
