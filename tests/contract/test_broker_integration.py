"""Integration test: bind the broker HTTP transport to the coordinator.

This end-to-end-in-memory test proves the broker product boundary is
internally consistent: a transport-level request walks through the principal
resolver, the coordinator's binding re-resolution, the form-based adapter,
and emits a status-only result back to the agent. Secret-bearing fields are
never returned.
"""

from __future__ import annotations

from cloudbrowser.credential_broker import BrokerResult, LoginIntent, SiteDeclaration
from cloudbrowser.credential_broker.adapters import CredentialMaterial, FormLoginAdapter, FormLoginDeclaration
from cloudbrowser.credential_broker.audit import AuditEmitter
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.service import ResolvedBinding


class _FakeFormBrowser:
    def __init__(self, url: str, visible: set[str], account_text: str = "") -> None:
        self.url = url
        self.visible = visible
        self.account_text = account_text
        self.calls: list[tuple[str, str, str]] = []

    def current_url(self) -> str:
        return self.url

    def has_selector(self, selector: str) -> bool:
        return selector in self.visible

    def fill(self, selector: str, value: str) -> None:
        self.calls.append(("fill", selector, value))

    def click(self, selector: str) -> None:
        self.calls.append(("click", selector, ""))

    def read_text(self, selector: str) -> str:
        assert selector == "[data-account]"
        return self.account_text


def _run_adapter(declaration: SiteDeclaration, material: CredentialMaterial) -> object:
    browser = _FakeFormBrowser(
        "https://login.example.test/start",
        {"#username", "#password", "button[type=submit]", "[data-authenticated]", "[data-account]"},
        "alice@example.test",
    )
    form_declaration = FormLoginDeclaration(
        site_id="site-a",
        origin="https://login.example.test",
        username_selector="#username",
        password_selector="#password",
        submit_selector="button[type=submit]",
        success_selector="[data-authenticated]",
        account_selector="[data-account]",
    )
    return FormLoginAdapter().execute(form_declaration, material, browser)


def test_transport_to_coordinator_round_trip_returns_status_only() -> None:
    emitter = AuditEmitter(component="credential-broker", instance_id="cloudbrowser-dev-v01")
    declaration = SiteDeclaration("site-a", "https://login.example.test")
    binding = ResolvedBinding(
        profile_id="profile-a",
        principal_id="alice@example.test",
        browser_id="browser-1",
        site_id="site-a",
        generation="g1",
    )
    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: binding,
        resolve_pre_fill=lambda _: binding,
        declarations={"site-a": declaration},
        adapter_selector=lambda site, decl: _run_adapter,
        emitter=emitter,
    )

    intent = LoginIntent(
        request_id="req-1",
        profile_id="profile-a",
        principal_id="alice@example.test",
        browser_id="browser-1",
        site_id="site-a",
        username_ref="account-ref",
        binding_generation="g1",
    )
    result = coordinator.execute(intent, fetch_credentials=lambda ref: CredentialMaterial("alice@example.test", "pw"))
    assert result == BrokerResult("req-1", "authenticated")

    # Public serialization must remain bounded.
    public = result.to_public_dict()
    assert set(public.keys()) == {"request_id", "status", "error_code", "duration_ms"}
    assert "pw" not in str(public)
