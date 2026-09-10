"""Fail-closed contracts for broker authorization dependencies."""

from __future__ import annotations

import pytest

from cloudbrowser.browser_slots.transport import BrowserUnavailable
from cloudbrowser.credential_broker import (
    AdapterResult,
    BrokerCoordinator,
    DependencyUnavailable,
    GrantAuthorization,
    LoginIntent,
    SiteDeclaration,
)
from cloudbrowser.credential_broker.service import ResolvedBinding

_BINDING = ResolvedBinding("profile-a", "principal-a", "browser-a", "site-a", "g1")
_INTENT = LoginIntent(
    request_id="request-a",
    profile_id="profile-a",
    principal_id="principal-a",
    browser_id="browser-a",
    site_id="site-a",
    target_tab_id="target-a",
    binding_generation="g1",
)


def _adapter(_: object, __: object) -> AdapterResult:
    return AdapterResult("authenticated", True)


def _grant(binding: ResolvedBinding, site_id: str, target_tab_id: str) -> GrantAuthorization:
    return GrantAuthorization(
        username_ref="item-a",
        profile_id=binding.profile_id,
        principal_id=binding.principal_id,
        browser_id=binding.browser_id,
        generation=binding.generation,
        site_id=site_id,
        target_tab_id=target_tab_id,
    )


def test_coordinator_requires_server_grant_resolver_and_exact_target_preflight() -> None:
    common = {
        "resolve_initial": lambda _: _BINDING,
        "resolve_pre_fill": lambda _: _BINDING,
        "declarations": {"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        "adapter_selector": lambda *_: _adapter,
    }
    with pytest.raises(TypeError):
        BrokerCoordinator(**common, target_preflight=lambda *_: object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BrokerCoordinator(**common, grant_resolver=_grant)  # type: ignore[arg-type]


def test_grant_authorization_requires_full_live_scope() -> None:
    with pytest.raises((TypeError, ValueError)):
        GrantAuthorization(  # type: ignore[call-arg]
            username_ref="item-a",
            principal_id="principal-a",
            site_id="site-a",
            target_tab_id="target-a",
        )


def test_preflight_runs_before_fetch_and_again_immediately_before_fill() -> None:
    phases: list[str] = []

    def preflight(_: LoginIntent, __: object) -> object:
        phases.append("target")
        return ("target-a", "https://login.example.test/")

    def fetch(_: str) -> object:
        phases.append("fetch")
        return object()

    def adapter(_: object, __: object) -> AdapterResult:
        phases.append("fill")
        return AdapterResult("authenticated", True)

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: _BINDING,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        adapter_selector=lambda *_: adapter,
        grant_resolver=_grant,
        target_preflight=preflight,
    )
    result = coordinator.execute(_INTENT, fetch_credentials=fetch)

    assert result.status == "authenticated"
    assert phases == ["target", "fetch", "target", "fill"]


def test_browser_dependency_failure_is_bounded_but_programmer_error_is_not_swallowed() -> None:
    def unavailable(_: LoginIntent) -> ResolvedBinding:
        raise BrowserUnavailable("sensitive dependency detail")

    coordinator = BrokerCoordinator(
        resolve_initial=unavailable,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        adapter_selector=lambda *_: _adapter,
        grant_resolver=_grant,
        target_preflight=lambda *_: object(),
    )
    result = coordinator.execute(_INTENT, fetch_credentials=lambda _: object())
    assert result.status == "failed"
    assert result.error_code == "browser_unavailable"
    assert "sensitive" not in str(result.to_public_dict())

    class UnavailableGrant:
        def resolve(
            self, binding: ResolvedBinding, site_id: str, target_tab_id: str
        ) -> GrantAuthorization:
            raise DependencyUnavailable("sensitive grant backend detail")

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: _BINDING,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        adapter_selector=lambda *_: _adapter,
        grant_resolver=UnavailableGrant(),
        target_preflight=lambda *_: object(),
    )
    result = coordinator.execute(_INTENT, fetch_credentials=lambda _: object())
    assert result.status == "failed"
    assert result.error_code == "dependency_unavailable"
    assert "sensitive" not in str(result.to_public_dict())

    def programmer_error(_: LoginIntent) -> ResolvedBinding:
        raise RuntimeError("programmer error")

    coordinator = BrokerCoordinator(
        resolve_initial=programmer_error,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        adapter_selector=lambda *_: _adapter,
        grant_resolver=_grant,
        target_preflight=lambda *_: object(),
    )
    with pytest.raises(RuntimeError, match="programmer error"):
        coordinator.execute(_INTENT, fetch_credentials=lambda _: object())
