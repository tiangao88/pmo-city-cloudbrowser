"""RED-stage tests for the HTTP Basic Auth broker adapter (PRD-BR-04).

These tests pin the bounded behavior required by the broker refactor:
- exact declared-origin only, no URL-credential smuggling;
- refresh/redirect chains permitted ONLY when declared; otherwise no fill;
- credential material never leaves the broker;
- status-only response, with bounded error code on every failure mode.
"""

from __future__ import annotations

import pytest

from cloudbrowser.credential_broker import AdapterResult
from cloudbrowser.credential_broker.adapters.basic import (
    BasicAuthAdapter,
    BasicAuthDeclaration,
    CredentialMaterial,
)


class FakeBasicBrowser:
    """In-memory double for a restricted browser capability."""

    def __init__(self, current_origin: str, authed_origin: str | None = None) -> None:
        self.current_origin = current_origin
        self.authed_origin = authed_origin
        self.calls: list[tuple[str, tuple]] = []

    def current_url(self) -> str:
        return self.current_origin

    def has_basic_auth_challenge(self, origin: str) -> bool:
        # A challenge is reported only when the fake was explicitly told
        # the authed origin matches the requested one. ``authed_origin=None``
        # therefore means "no challenge reported"; ``authed_origin=<url>``
        # means the challenge was answered on that origin.
        return self.authed_origin is not None and origin == self._origin_for(self.current_origin) and self.authed_origin == origin

    def _origin_for(self, url: str) -> str:
        if "://" not in url:
            return ""
        scheme, rest = url.split("://", 1)
        host_path = rest.split("/", 1)
        return f"{scheme}://{host_path[0]}"

    def submit_basic_auth(self, origin: str, username: str, password: str) -> None:
        self.calls.append(("submit_basic_auth", (origin, username, password)))
        if self.authed_origin is None:
            self.authed_origin = origin

    def clear_header(self, name: str) -> None:
        self.calls.append(("clear_header", (name,)))


def declaration(**overrides) -> BasicAuthDeclaration:
    values = {
        "site_id": "basic-test",
        "origin": "https://login.example.test",
        "redirect_origins": (),
        "username_ref": "user-ref",
    }
    values.update(overrides)
    return BasicAuthDeclaration(**values)


def credentials() -> CredentialMaterial:
    return CredentialMaterial(username="alice@example.test", password="pw")


def test_basic_adapter_succeeds_on_exact_declared_origin() -> None:
    browser = FakeBasicBrowser("https://login.example.test/", authed_origin="https://login.example.test")
    adapter = BasicAuthAdapter()
    result = adapter.execute(declaration(), credentials(), browser)
    assert result == AdapterResult("authenticated", True)
    assert browser.calls == [
        ("submit_basic_auth", ("https://login.example.test", "alice@example.test", "pw")),
    ]


def test_basic_adapter_rejects_http_origin() -> None:
    browser = FakeBasicBrowser("http://login.example.test/")
    adapter = BasicAuthAdapter()
    with pytest.raises(ValueError):
        adapter.execute(declaration(), credentials(), browser)
    assert browser.calls == []


def test_basic_adapter_rejects_origin_not_in_redirect_set() -> None:
    browser = FakeBasicBrowser("https://attacker.example.test/")
    adapter = BasicAuthAdapter()
    with pytest.raises(ValueError):
        adapter.execute(declaration(redirect_origins=("https://login.example.test",)), credentials(), browser)
    assert browser.calls == []


def test_basic_adapter_permits_explicit_redirect_origin() -> None:
    browser = FakeBasicBrowser("https://login.example.test/callback", authed_origin="https://login.example.test")
    adapter = BasicAuthAdapter()
    result = adapter.execute(
        declaration(redirect_origins=("https://login.example.test",)),
        credentials(),
        browser,
    )
    assert result.status == "authenticated"


def test_basic_adapter_returns_when_no_challenge_present() -> None:
    browser = FakeBasicBrowser("https://login.example.test/", authed_origin="https://other.example.test/")
    adapter = BasicAuthAdapter()
    # Browser never reported a challenge - the adapter must NOT auto-fill.
    result = adapter.execute(declaration(), credentials(), browser)
    assert result.status == "failed"
    assert result.identity_verified is False
    assert browser.calls == []


def test_basic_adapter_does_not_embed_credentials_in_failure_strings() -> None:
    browser = FakeBasicBrowser("http://login.example.test/")
    adapter = BasicAuthAdapter()
    try:
        adapter.execute(declaration(), credentials(), browser)
    except ValueError as exc:
        for forbidden in ("alice@example.test", "pw"):
            assert forbidden not in str(exc)
    else:
        pytest.fail("expected ValueError")
