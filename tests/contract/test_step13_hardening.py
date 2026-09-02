"""RED-stage hardening contracts for the generic credential broker."""

from __future__ import annotations

from dataclasses import dataclass

from cloudbrowser.credential_broker import AdapterResult, BrokerResult, LoginIntent, SiteDeclaration
from cloudbrowser.credential_broker.adapters.basic import BasicAuthAdapter, BasicAuthDeclaration, CredentialMaterial as BasicMaterial
from cloudbrowser.credential_broker.adapters.human_handoff import (
    HumanHandoffStore,
    human_handoff_request,
    human_handoff_submit,
)
from cloudbrowser.credential_broker.adapters.sso import SSOAdapter, SSODeclaration
from cloudbrowser.credential_broker.adapters.totp import TOTPAdapter, TOTPDeclaration, TOTPMaterial, compute_totp
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.service import ResolvedBinding


class BasicBrowser:
    def __init__(self, urls: list[str], challenges: list[str | None], authenticated: bool = True) -> None:
        self.urls = urls
        self.challenges = challenges
        self.authenticated = authenticated
        self.index = 0
        self.calls: list[tuple[str, str, str]] = []

    def current_url(self) -> str:
        return self.urls[min(self.index, len(self.urls) - 1)]

    def challenge_origin(self) -> str | None:
        return self.challenges[min(self.index, len(self.challenges) - 1)]

    def has_basic_auth_challenge(self, origin: str) -> bool:
        return self.challenge_origin() == origin

    def submit_basic_auth(self, origin: str, username: str, password: str) -> None:
        self.calls.append((origin, username, password))
        self.index += 1

    def application_authenticated(self) -> bool:
        return self.authenticated


class TOTPBrowser:
    def __init__(self, authenticated: bool = True) -> None:
        self.authenticated = authenticated
        self.filled: list[tuple[str, str]] = []
        self.clicked: list[str] = []

    def current_url(self) -> str:
        return "https://login.example.test/mfa"

    def has_selector(self, selector: str) -> bool:
        return selector in {"[name=code]", "button[type=submit]"}

    def fill_code(self, selector: str, value: str) -> None:
        self.filled.append((selector, value))

    def click(self, selector: str) -> None:
        self.clicked.append(selector)

    def application_authenticated(self) -> bool:
        return self.authenticated


class SSOBrowser:
    def __init__(
        self,
        *,
        current_url: str = "https://idp.example.test/login",
        idp_ok: bool = True,
        app_identity: str | None = "alice@example.test",
        mfa_modality: str | None = None,
    ) -> None:
        self.url = current_url
        self.idp_ok = idp_ok
        self.app_identity = app_identity
        self.mfa_modality = mfa_modality
        self.calls: list[tuple[str, str, str]] = []

    def current_url(self) -> str:
        return self.url

    def begin_login(self, origin: str, username: str, password: str) -> None:
        self.calls.append((origin, username, password))
        self.idp_ok = True

    def idp_authenticated(self) -> bool:
        return self.idp_ok

    def application_identity(self) -> str | None:
        return self.app_identity

    def mfa_challenge(self) -> str | None:
        return self.mfa_modality


@dataclass
class _Clock:
    value: float

    def __call__(self) -> float:
        return self.value


def sso_declaration(**overrides) -> SSODeclaration:
    values = {
        "site_id": "sso-test",
        "idp_origins": ("https://idp.example.test",),
        "callback_origins": ("https://app.example.test",),
        "application_origins": ("https://app.example.test",),
        "login_path": "/login",
        "adapter_version": "sso/v1",
        "allowed_mfa": ("totp", "human_handoff"),
    }
    values.update(overrides)
    return SSODeclaration(**values)


def material() -> BasicMaterial:
    return BasicMaterial("alice@example.test", "synthetic-password")


def test_basic_auth_requires_a_challenge_and_application_proof() -> None:
    browser = BasicBrowser(
        ["https://login.example.test/", "https://login.example.test/home"],
        ["https://login.example.test", None],
    )
    result = BasicAuthAdapter().execute(
        BasicAuthDeclaration("basic", "https://login.example.test"), material(), browser
    )
    assert result == AdapterResult("authenticated", True)
    assert browser.calls == [("https://login.example.test", "alice@example.test", "synthetic-password")]


def test_basic_auth_fails_closed_on_a_challenge_loop() -> None:
    browser = BasicBrowser(
        ["https://login.example.test/", "https://login.example.test/"],
        ["https://login.example.test", "https://login.example.test"],
    )
    result = BasicAuthAdapter().execute(
        BasicAuthDeclaration("basic", "https://login.example.test"), material(), browser
    )
    assert result == AdapterResult("failed", False, "challenge_loop")
    assert len(browser.calls) == 1


def test_basic_auth_fails_closed_on_origin_change() -> None:
    browser = BasicBrowser(
        ["https://login.example.test/", "https://attacker.example.test/"],
        ["https://login.example.test", None],
    )
    result = BasicAuthAdapter().execute(
        BasicAuthDeclaration("basic", "https://login.example.test"), material(), browser
    )
    assert result == AdapterResult("failed", False, "origin_changed")


def test_basic_auth_does_not_claim_success_without_application_proof() -> None:
    browser = BasicBrowser(
        ["https://login.example.test/", "https://login.example.test/home"],
        ["https://login.example.test", None],
        authenticated=False,
    )
    result = BasicAuthAdapter().execute(
        BasicAuthDeclaration("basic", "https://login.example.test"), material(), browser
    )
    assert result == AdapterResult("failed", False, "success_unverified")


def test_totp_matches_rfc6238_sha1_vectors() -> None:
    secret = b"12345678901234567890"
    vectors = {
        59: "287082",
        1_111_111_109: "081804",
        1_111_111_111: "050471",
        1_234_567_890: "005924",
        2_000_000_000: "279037",
        20_000_000_000: "353130",
    }
    for timestamp, expected in vectors.items():
        assert compute_totp(secret, timestamp, period=30, digits=6) == expected


def test_totp_does_not_claim_success_without_application_proof() -> None:
    browser = TOTPBrowser(authenticated=False)
    result = TOTPAdapter().execute(
        TOTPDeclaration("totp", "https://login.example.test", "[name=code]", "button[type=submit]"),
        TOTPMaterial(b"12345678901234567890"), browser, 59
    )
    assert result == AdapterResult("failed", False, "success_unverified")
    assert browser.filled == [("[name=code]", "287082")]


def test_human_handoff_is_ttl_bound_and_single_use() -> None:
    clock = _Clock(100.0)
    store = HumanHandoffStore(clock=clock, ttl_seconds=180)
    token = human_handoff_request(store, principal_id="alice@example.test", site_id="site-a", generation="g1")
    assert human_handoff_submit(
        store, principal_id="alice@example.test", site_id="site-a", generation="g1",
        token=token, code="123456", verify_code=lambda value: value == "123456",
    ) == "authenticated"
    assert human_handoff_submit(
        store, principal_id="alice@example.test", site_id="site-a", generation="g1",
        token=token, code="123456", verify_code=lambda value: True,
    ) == "failed"
    expired = human_handoff_request(store, principal_id="alice@example.test", site_id="site-a", generation="g1")
    clock.value = 281.0
    assert human_handoff_submit(
        store, principal_id="alice@example.test", site_id="site-a", generation="g1",
        token=expired, code="123456", verify_code=lambda value: True,
    ) == "failed"
    assert "123456" not in repr(store)


def test_human_handoff_wrong_binding_does_not_consume_the_challenge() -> None:
    store = HumanHandoffStore(clock=lambda: 100.0, ttl_seconds=180)
    token = human_handoff_request(store, principal_id="alice@example.test", site_id="site-a", generation="g1")
    assert human_handoff_submit(
        store, principal_id="bob@example.test", site_id="site-a", generation="g1",
        token=token, code="123456", verify_code=lambda value: True,
    ) == "failed"
    assert human_handoff_submit(
        store, principal_id="alice@example.test", site_id="site-a", generation="g1",
        token=token, code="123456", verify_code=lambda value: True,
    ) == "authenticated"


def test_sso_requires_idp_origin_before_any_credential_fill() -> None:
    browser = SSOBrowser(current_url="https://attacker.example.test/login")
    result = SSOAdapter().execute(sso_declaration(), material(), browser, expected_account="alice@example.test")
    assert result == AdapterResult("failed", False, "invalid_target")
    assert browser.calls == []


def test_sso_idp_success_without_application_identity_is_not_success() -> None:
    browser = SSOBrowser(app_identity=None)
    result = SSOAdapter().execute(sso_declaration(), material(), browser, expected_account="alice@example.test")
    assert result == AdapterResult("failed", False, "success_unverified")


def test_sso_wrong_application_identity_fails_closed() -> None:
    # IdP authentication is true in this fixture, so only application identity
    # matching decides whether the broker may claim success.
    browser = SSOBrowser(
        current_url="https://app.example.test/home",
        app_identity="bob@example.test",
    )
    result = SSOAdapter().execute(sso_declaration(), material(), browser, expected_account="alice@example.test")
    assert result == AdapterResult("failed", False, "identity_mismatch")


def test_sso_unsupported_mfa_does_not_fill_or_claim_success() -> None:
    browser = SSOBrowser(mfa_modality="webauthn")
    result = SSOAdapter().execute(sso_declaration(), material(), browser, expected_account="alice@example.test")
    assert result == AdapterResult("unsupported", False, "mfa_unsupported")
    assert browser.calls == []


def test_sso_success_requires_idp_and_application_identity() -> None:
    browser = SSOBrowser(current_url="https://app.example.test/home", idp_ok=False)
    result = SSOAdapter().execute(sso_declaration(), material(), browser, expected_account="alice@example.test")
    assert result == AdapterResult("authenticated", True)
    assert browser.calls == [("https://idp.example.test", "alice@example.test", "synthetic-password")]


def test_coordinator_revalidates_after_credential_fetch() -> None:
    phases: list[str] = []
    initial = ResolvedBinding("profile-a", "alice@example.test", "browser-1", "site-a", "g1")
    declaration = SiteDeclaration("site-a", "https://login.example.test")
    intent = LoginIntent("req-hardening", "profile-a", "alice@example.test", "browser-1", "site-a", "account-ref", binding_generation="g1")

    def fetch(_: str) -> object:
        phases.append("fetch")
        return object()

    def resolve_pre_fill(_: LoginIntent) -> ResolvedBinding:
        assert phases == ["fetch"]
        return ResolvedBinding("profile-a", "alice@example.test", "browser-1", "site-a", "g2")

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: initial,
        resolve_pre_fill=resolve_pre_fill,
        declarations={"site-a": declaration},
        adapter_selector=lambda site, decl: lambda declaration, material: AdapterResult("authenticated", True),
    )
    result = coordinator.execute(intent, fetch_credentials=fetch)
    assert result == BrokerResult("req-hardening", "failed", "stale_binding")
