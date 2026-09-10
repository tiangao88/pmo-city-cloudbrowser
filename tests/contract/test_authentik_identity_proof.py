"""Application-specific identity proof contracts for Authentik SSO."""

from __future__ import annotations

import pytest

from cloudbrowser.browser_slots.authentik import AuthentikCapability
from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.adapters.sso import (
    AuthentikSSOAdapter,
    AuthentikSSODeclaration,
)
from cloudbrowser.credential_broker.service import AdapterResult


class _ProofActions:
    def __init__(self, *, found: bool, text: str = "", value: str = "") -> None:
        self.found = found
        self.text = text
        self.value = value
        self.calls: list[tuple[str, str | None]] = []

    def broker_authentik_proof(
        self,
        target_id: str,
        *,
        application_origins: tuple[str, ...],
        success_paths: tuple[str, ...],
        selector: str,
        claim: str,
    ):
        self.calls.append((target_id, selector))
        assert application_origins == ("https://app.example.test",)
        assert success_paths == ("/authenticated",)
        assert claim == "attribute:data-account-id"
        return {
            "account": self.value if self.found else None,
            "url": "https://app.example.test/authenticated",
        }

    def broker_navigate(self, target_id, url):
        raise AssertionError((target_id, url))

    def broker_authentik_identification(self, target_id, **kwargs):
        raise AssertionError((target_id, kwargs))

    def broker_authentik_rejection(self, target_id, **kwargs):
        raise AssertionError((target_id, kwargs))

    def broker_page_info(self, target_id, selector=None):
        raise AssertionError((target_id, selector))

    def broker_click(self, target_id, selector):
        raise AssertionError((target_id, selector))

    def broker_type_text(self, target_id, selector, text):
        raise AssertionError((target_id, selector, text))


def _capability(actions: _ProofActions) -> AuthentikCapability:
    return AuthentikCapability(
        actions,
        ("https://auth.example.test",),
        ("https://app.example.test",),
        ("/authenticated",),
        identity_selector="[data-account-id]",
        identity_claim="attribute:data-account-id",
    )


def test_exact_target_application_identity_proof_succeeds() -> None:
    actions = _ProofActions(found=True, value="alice@example.test")
    assert _capability(actions).proof(target_id="target-exact") == {
        "account": "alice@example.test"
    }
    assert actions.calls[-1] == ("target-exact", "[data-account-id]")


def test_exact_target_application_identity_proof_is_missing() -> None:
    actions = _ProofActions(found=False)
    assert _capability(actions).proof(target_id="target-exact") == {"account": None}


def _declaration(**overrides: object) -> AuthentikSSODeclaration:
    values: dict[str, object] = {
        "site_id": "authentik-app",
        "entry_url": "https://auth.example.test/if/flow/default-authentication-flow/",
        "idp_origins": ("https://auth.example.test",),
        "callback_origins": ("https://app.example.test",),
        "application_origins": ("https://app.example.test",),
        "application_success_paths": ("/authenticated",),
        "application_identity_selector": "[data-account-id]",
        "application_identity_claim": "attribute:data-account-id",
    }
    values.update(overrides)
    return AuthentikSSODeclaration(**values)  # type: ignore[arg-type]


class _ApplicationBrowser:
    def __init__(self, account: str | None) -> None:
        self.account = account

    def current_url(self) -> str:
        return "https://app.example.test/authenticated?private=yes#fragment"

    def begin_authentik(self, entry_url: str) -> None:
        raise AssertionError(entry_url)

    def identification(self, username: str, password: str) -> str:
        raise AssertionError((username, password))

    def application_identity(self) -> str | None:
        return self.account

    def mfa_stage(self) -> str | None:
        return None


def test_declared_application_identity_missing_fails_closed() -> None:
    result = AuthentikSSOAdapter().execute(
        _declaration(),
        CredentialMaterial("alice@example.test", "password"),
        _ApplicationBrowser(None),
        expected_account="alice@example.test",
    )
    assert result == AdapterResult("failed", False, "success_unverified")


def test_declared_application_identity_mismatch_fails_closed() -> None:
    result = AuthentikSSOAdapter().execute(
        _declaration(),
        CredentialMaterial("alice@example.test", "password"),
        _ApplicationBrowser("mallory@example.test"),
        expected_account="alice@example.test",
    )
    assert result == AdapterResult("failed", False, "identity_mismatch")


def test_declared_application_identity_match_authenticates() -> None:
    result = AuthentikSSOAdapter().execute(
        _declaration(),
        CredentialMaterial("alice@example.test", "password"),
        _ApplicationBrowser("alice@example.test"),
        expected_account="alice@example.test",
    )
    assert result == AdapterResult("authenticated", True)


def test_declared_application_identity_comparison_canonicalizes_both_sides() -> None:
    result = AuthentikSSOAdapter().execute(
        _declaration(),
        CredentialMaterial("Alice@EXAMPLE.TEST ", "password"),
        _ApplicationBrowser(" alice@example.test "),
        expected_account="Alice@EXAMPLE.TEST ",
    )
    assert result == AdapterResult("authenticated", True)


def test_declared_application_identity_rejects_invalid_expected_or_observed() -> None:
    for expected_account, observed_account in (
        ("alice@example", "alice@example"),
        ("alice@example.test\n", "alice@example.test"),
        ("alice@example.test", "alice＠example.test"),
    ):
        result = AuthentikSSOAdapter().execute(
            _declaration(),
            CredentialMaterial("alice@example.test", "password"),
            _ApplicationBrowser(observed_account),
            expected_account=expected_account,
        )
        assert result == AdapterResult("failed", False, "identity_invalid")


@pytest.mark.parametrize(
    ("selector", "claim"),
    [
        ("", "attribute:data-account-id"),
        ("[data-account-id]", ""),
        ("*", "attribute:data-account-id"),
        ("[data-account-id]", "html"),
        ("[data-account-id]", "attribute:onmouseover"),
    ],
)
def test_identity_proof_declaration_rejects_unsafe_or_incomplete_rules(
    selector: str, claim: str
) -> None:
    with pytest.raises(ValueError):
        _declaration(
            application_identity_selector=selector,
            application_identity_claim=claim,
        )
