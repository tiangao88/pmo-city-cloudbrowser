"""Contract tests for live, server-authoritative broker binding.

The request intentionally carries stale boot-time identity assertions. The
broker must ignore those values as authority, resolve the live browser binding,
and execute only against that server-owned binding.
"""

from __future__ import annotations

from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.grant_store import DurableGrantStore
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.runtime import LiveBrowserBinding, build_broker_api
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability


class _LiveBasicBrowser:
    def __init__(self) -> None:
        self.url = "https://basic.example.test/protected"
        self.challenge = "https://basic.example.test"
        self.authenticated = False
        self.calls: list[tuple[str, str, str, str]] = []

    def live_binding(self) -> LiveBrowserBinding:
        return LiveBrowserBinding(
            profile_id="profile-live",
            principal_id="pmo-live",
            browser_id="browser-slot-1",
            generation="generation-live",
        )

    def current_url(self, *, target_id: str) -> str:
        return self.url

    def challenge_origin(self, *, target_id: str) -> str | None:
        return self.challenge

    def submit_basic_auth(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
    ) -> None:
        self.calls.append((origin, username, target_id, success_path))
        self.url = "https://basic.example.test/authenticated"
        self.challenge = None
        self.authenticated = True

    def application_authenticated(self, *, target_id: str) -> bool:
        return self.authenticated


def _configure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CB_INSTANCE_ID", "dynamic-binding-test")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "pmo-static-wrong")
    monkeypatch.setenv("CB_PROFILE_ID", "profile-static-wrong")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-slot-1")
    monkeypatch.setenv("CB_BINDING_GENERATION", "generation-static-wrong")
    monkeypatch.setenv("CB_CREDENTIAL_CAPABILITY_SECRET", "capability-secret-0123456789")
    monkeypatch.setenv("CB_CREDENTIAL_BROKER_AUDIENCE", "credential-broker")
    monkeypatch.setenv("CB_BROKER_GRANT_DB_PATH", str(tmp_path / "grants.sqlite3"))
    monkeypatch.setenv("CB_BROKER_IDEMPOTENCY_DB_PATH", str(tmp_path / "idempotency.sqlite3"))
    monkeypatch.setenv("CB_CREDENTIAL_NONCE_DB_PATH", str(tmp_path / "nonces.sqlite3"))
    monkeypatch.setenv("CB_BROKER_SUBMIT_SECRET", "submit-secret-0123456789abcdef")
    monkeypatch.setenv("CB_BROKER_ADAPTER", "basic")
    monkeypatch.setenv("CB_BROKER_SITE_ID", "basic-site")
    monkeypatch.setenv("CB_BROKER_ORIGIN", "https://basic.example.test")
    monkeypatch.setenv("CB_BROKER_SUCCESS_PATH", "/authenticated")


def test_broker_compares_capability_binding_to_live_browser(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    browser = _LiveBasicBrowser()
    capability = CredentialCapability(
        profile_id="profile-live",
        principal_id="pmo-live",
        browser_id="browser-slot-1",
        generation="generation-live",
        site_id="basic-site",
        target_tab_id="target-1",
        operation="credential.login",
        request_id="request-live-binding",
        audience="credential-broker",
        deployment="dynamic-binding-test",
        issued_at=1000,
        expires_at=1030,
        nonce="nonce-live-binding",
    )
    grants = DurableGrantStore(tmp_path / "grants.sqlite3")
    grants.put(
        profile_id="profile-live",
        principal_id="pmo-live",
        site_id="basic-site",
        target_tab_id="target-1",
        browser_id="browser-slot-1",
        generation="generation-live",
        username_ref="basic-item",
    )
    api = build_broker_api(
        browser_factory=lambda: browser,
        credential_fetcher=lambda ref: CredentialMaterial("alice", "secret-pw"),
        grant_resolver=grants,
        nonce_store=DurableNonceStore(tmp_path / "nonces.sqlite3"),
        idempotency_store=DurableIdempotencyStore(tmp_path / "idempotency.sqlite3"),
        clock=lambda: 1001,
    )

    with api.handle(
        "/v1/credential/login",
        {"capability": CapabilityCodec("capability-secret-0123456789").encode(capability)},
    ) as response:
        body = dict(response.body)

    assert body["status"] == "authenticated"
    assert body["error_code"] is None
    assert browser.calls == [("https://basic.example.test", "alice", "target-1", "/authenticated")]
