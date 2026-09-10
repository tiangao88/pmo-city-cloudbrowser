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
from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded


def test_basic_adapter_stops_before_side_effect_when_budget_expires_during_probe() -> None:
    class ExpiringBrowser:
        def current_url(self, *, target_id: str) -> str:
            return "https://basic.example.test/protected"

        def challenge_origin(self, *, target_id: str) -> str:
            clock[0] = 2.0
            return "https://basic.example.test"

        def submit_basic_auth(self, *args, **kwargs) -> None:
            raise AssertionError("credential side effect must not start after deadline")

    clock = [1.0]
    deadline = BrokerDeadline(1.5, monotonic_clock=lambda: clock[0])
    declaration = BasicAuthDeclaration(
        site_id="basic",
        origin="https://basic.example.test",
        success_path="/home",
    )
    with pytest.raises(BrokerDeadlineExceeded):
        BasicAuthAdapter().execute(
            declaration,
            CredentialMaterial("alice", "secret"),
            ExpiringBrowser(),
            target_id="target-1",
            deadline=deadline,
        )


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

    def current_url(self, *, target_id: str = "target-1") -> str:
        return self.current_origin

    def has_basic_auth_challenge(
        self, origin: str, *, target_id: str = "target-1"
    ) -> bool:
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

    def submit_basic_auth(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str = "target-1",
        success_path: str = "/",
    ) -> None:
        self.calls.append(("submit_basic_auth", (origin, username, password)))
        if self.authed_origin is None:
            self.authed_origin = origin

    def application_authenticated(self, *, target_id: str = "target-1") -> bool:
        return self.authed_origin == self._origin_for(self.current_origin)

    def clear_header(self, name: str) -> None:
        self.calls.append(("clear_header", (name,)))


def declaration(**overrides) -> BasicAuthDeclaration:
    values = {
        "site_id": "basic-test",
        "origin": "https://login.example.test",
        "redirect_origins": (),
        "username_ref": "user-ref",
        "success_path": "/",
    }
    values.update(overrides)
    return BasicAuthDeclaration(**values)


def credentials() -> CredentialMaterial:
    return CredentialMaterial(username="alice@example.test", password="pw")


def test_basic_adapter_succeeds_on_exact_declared_origin() -> None:
    browser = FakeBasicBrowser("https://login.example.test/", authed_origin="https://login.example.test")
    adapter = BasicAuthAdapter()
    result = adapter.execute(declaration(), credentials(), browser, target_id="target-1")
    assert result == AdapterResult("authenticated", True)
    assert browser.calls == [
        ("submit_basic_auth", ("https://login.example.test", "alice@example.test", "pw")),
    ]


def test_basic_adapter_rejects_http_origin() -> None:
    browser = FakeBasicBrowser("http://login.example.test/")
    adapter = BasicAuthAdapter()
    with pytest.raises(ValueError):
        adapter.execute(declaration(), credentials(), browser, target_id="target-1")
    assert browser.calls == []


def test_basic_adapter_rejects_origin_not_in_redirect_set() -> None:
    browser = FakeBasicBrowser("https://attacker.example.test/")
    adapter = BasicAuthAdapter()
    with pytest.raises(ValueError):
        adapter.execute(
            declaration(redirect_origins=("https://login.example.test",)),
            credentials(),
            browser,
            target_id="target-1",
        )
    assert browser.calls == []


def test_basic_adapter_permits_explicit_redirect_origin() -> None:
    browser = FakeBasicBrowser("https://login.example.test/callback", authed_origin="https://login.example.test")
    adapter = BasicAuthAdapter()
    result = adapter.execute(
        declaration(redirect_origins=("https://login.example.test",)),
        credentials(),
        browser,
        target_id="target-1",
    )
    assert result.status == "authenticated"


def test_basic_adapter_returns_when_no_challenge_present() -> None:
    browser = FakeBasicBrowser("https://login.example.test/", authed_origin="https://other.example.test/")
    adapter = BasicAuthAdapter()
    # Browser never reported a challenge - the adapter must NOT auto-fill.
    result = adapter.execute(declaration(), credentials(), browser, target_id="target-1")
    assert result.status == "failed"
    assert result.identity_verified is False
    assert browser.calls == []


def test_basic_adapter_does_not_embed_credentials_in_failure_strings() -> None:
    browser = FakeBasicBrowser("http://login.example.test/")
    adapter = BasicAuthAdapter()
    try:
        adapter.execute(declaration(), credentials(), browser, target_id="target-1")
    except ValueError as exc:
        for forbidden in ("alice@example.test", "pw"):
            assert forbidden not in str(exc)
    else:
        pytest.fail("expected ValueError")
