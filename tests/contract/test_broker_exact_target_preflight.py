"""Contract tests for exact-target browser preflight."""

from __future__ import annotations

import pytest

from cloudbrowser.credential_broker import LoginIntent, SiteDeclaration
from cloudbrowser.credential_broker.runtime import BrowserTargetPreflight


_INTENT = LoginIntent(
    request_id="request-a",
    profile_id="profile-a",
    principal_id="principal-a",
    browser_id="browser-a",
    site_id="site-a",
    target_tab_id="target-a",
    binding_generation="generation-a",
)
_DECLARATION = SiteDeclaration("site-a", "https://login.example.test")


def test_preflight_uses_named_target_not_ambient_active_page() -> None:
    class Browser:
        def list_pages(self):
            return [
                {"tab_id": "ambient", "url": "https://evil.example/", "title": "evil"},
                {
                    "tab_id": "target-a",
                    "url": "https://login.example.test/form",
                    "title": "login",
                },
            ]

    proof = BrowserTargetPreflight(lambda: Browser()).preflight(_INTENT, _DECLARATION)
    assert proof == ("target-a", "https://login.example.test/form")


def test_preflight_rejects_browser_api_that_can_only_read_active_page() -> None:
    class AmbientOnlyBrowser:
        def current_url(self):
            return "https://login.example.test/form"

    with pytest.raises(ValueError, match="target-scoped"):
        BrowserTargetPreflight(lambda: AmbientOnlyBrowser()).preflight(_INTENT, _DECLARATION)


def test_preflight_rejects_missing_duplicate_or_wrong_origin_target() -> None:
    pages = [
        {"tab_id": "other", "url": "https://login.example.test/", "title": "other"}
    ]

    class Browser:
        def list_pages(self):
            return pages

    preflight = BrowserTargetPreflight(lambda: Browser())
    with pytest.raises(ValueError):
        preflight.preflight(_INTENT, _DECLARATION)

    pages[:] = [
        {"tab_id": "target-a", "url": "https://login.example.test/a", "title": "a"},
        {"tab_id": "target-a", "url": "https://login.example.test/b", "title": "b"},
    ]
    with pytest.raises(ValueError):
        preflight.preflight(_INTENT, _DECLARATION)

    pages[:] = [
        {"tab_id": "target-a", "url": "https://evil.example/", "title": "evil"}
    ]
    with pytest.raises(ValueError):
        preflight.preflight(_INTENT, _DECLARATION)
