"""Grant authorization and target-preflight contracts for the broker."""

from __future__ import annotations

from cloudbrowser.credential_broker import (
    AdapterResult,
    GrantAuthorization,
    LoginIntent,
    SiteDeclaration,
)
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.contracts import AuthorizationChanged
from cloudbrowser.credential_broker.service import ResolvedBinding


_BINDING = ResolvedBinding(
    profile_id="profile-a",
    principal_id="principal-a",
    browser_id="browser-a",
    site_id="site-a",
    generation="g1",
)
_INTENT = LoginIntent(
    request_id="grant-preflight-1",
    profile_id="profile-a",
    principal_id="principal-a",
    browser_id="browser-a",
    site_id="site-a",
    # This is deliberately attacker-controlled legacy input. It must never be
    # passed to fetch_credentials.
    username_ref="attacker-selected-item",
    target_tab_id="target-a",
    binding_generation="g1",
)
_DECLARATION = SiteDeclaration("site-a", "https://login.example.test")


def _grant_resolver(binding, site_id, target_tab_id):
    assert binding == _BINDING
    assert site_id == "site-a"
    assert target_tab_id == "target-a"
    return GrantAuthorization(
        username_ref="server-authorized-item",
        profile_id=binding.profile_id,
        principal_id=binding.principal_id,
        browser_id=binding.browser_id,
        generation=binding.generation,
        site_id=site_id,
        target_tab_id=target_tab_id,
    )


def test_grant_resolution_and_actual_target_preflight_precede_fetch() -> None:
    phases: list[tuple[str, object]] = []

    def resolve_initial(intent):
        phases.append(("binding", intent.username_ref))
        return _BINDING

    def resolve_pre_fill(intent):
        phases.append(("binding-pre-fill", intent.username_ref))
        return _BINDING

    def resolve_grant(binding, site_id, target_tab_id):
        phases.append(("grant", binding.principal_id, site_id, target_tab_id))
        return _grant_resolver(binding, site_id, target_tab_id)

    def preflight(intent, declaration):
        phases.append(("target", intent.target_tab_id, declaration.site_id))
        return "target-proof-v1"

    def fetch(username_ref):
        phases.append(("fetch", username_ref))
        return object()

    def adapter(declaration, material):
        phases.append(("adapter", material))
        return AdapterResult("authenticated", True)

    coordinator = BrokerCoordinator(
        resolve_initial=resolve_initial,
        resolve_pre_fill=resolve_pre_fill,
        declarations={"site-a": _DECLARATION},
        adapter_selector=lambda site, declaration, intent: adapter,
        grant_resolver=resolve_grant,
        target_preflight=preflight,
    )

    result = coordinator.execute(_INTENT, fetch_credentials=fetch)

    assert result.status == "authenticated"
    assert ("fetch", "server-authorized-item") in phases
    assert ("fetch", "attacker-selected-item") not in phases
    assert phases.index(("target", "target-a", "site-a")) < phases.index(
        ("fetch", "server-authorized-item")
    )
    assert phases[-1][0] == "adapter"


def test_target_preflight_failure_happens_before_credential_fetch() -> None:
    fetched: list[str] = []

    def preflight(intent, declaration):
        raise ValueError("target is no longer the declared target")

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: _BINDING,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": _DECLARATION},
        adapter_selector=lambda site, declaration, intent: lambda d, m: AdapterResult(
            "authenticated", True
        ),
        grant_resolver=_grant_resolver,
        target_preflight=preflight,
    )

    result = coordinator.execute(
        _INTENT,
        fetch_credentials=lambda ref: fetched.append(ref),
    )

    assert result.status == "failed"
    assert result.error_code == "invalid_target"
    assert fetched == []


def test_grant_target_and_binding_are_revalidated_before_adapter() -> None:
    phases: list[str] = []
    grant_calls = 0
    target_calls = 0

    def resolve_grant(binding, site_id, target_tab_id):
        nonlocal grant_calls
        grant_calls += 1
        phases.append("grant")
        return GrantAuthorization(
            username_ref="server-authorized-item" if grant_calls == 1 else "changed-item",
            profile_id=binding.profile_id,
            principal_id=binding.principal_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
            site_id=site_id,
            target_tab_id=target_tab_id,
        )

    def preflight(intent, declaration):
        nonlocal target_calls
        target_calls += 1
        phases.append("target")
        return f"proof-{target_calls}"

    adapter_calls: list[object] = []
    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: _BINDING,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": _DECLARATION},
        adapter_selector=lambda site, declaration, intent: lambda d, m: (
            adapter_calls.append(m) or AdapterResult("authenticated", True)
        ),
        grant_resolver=resolve_grant,
        target_preflight=preflight,
    )

    result = coordinator.execute(_INTENT, fetch_credentials=lambda _: object())

    assert result.status == "failed"
    assert result.error_code == "grant_changed"
    assert adapter_calls == []
    assert phases == ["target", "grant", "grant"]


def test_revocation_after_initial_resolution_prevents_vault_fetch() -> None:
    from cloudbrowser.credential_broker.grant_store import DurableGrantStore
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        store = DurableGrantStore(Path(directory) / "grants.sqlite3")
        store.put(
            profile_id="profile-a",
            principal_id="principal-a",
            site_id="site-a",
            target_tab_id="target-a",
            browser_id="browser-a",
            generation="g1",
            username_ref="server-authorized-item",
        )
        calls = 0
        fetched: list[str] = []

        def resolve_grant(binding, site_id, target_tab_id):
            nonlocal calls
            calls += 1
            if calls == 2:
                assert store.revoke(
                    profile_id="profile-a",
                    principal_id="principal-a",
                    site_id="site-a",
                    target_tab_id="target-a",
                ) is True
                raise LookupError("grant revoked")
            return store.resolve(binding, site_id, target_tab_id)

        coordinator = BrokerCoordinator(
            resolve_initial=lambda _: _BINDING,
            resolve_pre_fill=lambda _: _BINDING,
            declarations={"site-a": _DECLARATION},
            adapter_selector=lambda *_: lambda d, m: AdapterResult("authenticated", True),
            grant_resolver=resolve_grant,
            target_preflight=lambda *_: "target-proof-v1",
        )

        result = coordinator.execute(
            _INTENT,
            fetch_credentials=lambda ref: fetched.append(ref) or object(),
        )

    assert result.status == "not_shared"
    assert result.error_code == "grant_revoked"
    assert fetched == []


class _AuthorizationGate:
    def __init__(self, authorization: GrantAuthorization) -> None:
        self.authorization = authorization
        self.revoked = False
        self.entered = 0
        self.before_authorize = lambda: None

    def resolve(self, binding, site_id, target_tab_id):
        return self.authorization

    def run_authorized(self, authorization, operation):
        self.entered += 1
        self.before_authorize()
        if self.revoked:
            raise LookupError("grant revoked")
        if authorization != self.authorization:
            raise AuthorizationChanged("grant changed")
        return operation(object())


def test_adapter_uses_gate_material_not_the_earlier_fetch_result() -> None:
    authorization = _grant_resolver(_BINDING, "site-a", "target-a")
    gate = _AuthorizationGate(authorization)
    gate.supplies_material = True
    gated_material = object()
    fetch_calls: list[str] = []
    seen: list[object] = []
    gate.run_authorized = lambda current, operation: operation(gated_material)  # type: ignore[method-assign]

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: _BINDING,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": _DECLARATION},
        adapter_selector=lambda *_: lambda declaration, material: (
            seen.append(material) or AdapterResult("authenticated", True)
        ),
        grant_resolver=gate,
        target_preflight=lambda *_: "target-proof-v1",
        authorization_gate=gate,
    )

    result = coordinator.execute(
        _INTENT,
        fetch_credentials=lambda ref: fetch_calls.append(ref) or object(),
    )

    assert result.status == "authenticated"
    assert seen == [gated_material]
    assert fetch_calls == []


def test_revocation_after_final_recheck_is_rejected_inside_side_effect_gate() -> None:
    adapter_calls: list[object] = []
    authorization = _grant_resolver(_BINDING, "site-a", "target-a")
    gate = _AuthorizationGate(authorization)
    gate.before_authorize = lambda: setattr(gate, "revoked", True)

    def preflight(intent, declaration):
        return "target-proof-v1"

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: _BINDING,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": _DECLARATION},
        adapter_selector=lambda *_: lambda declaration, material: (
            adapter_calls.append(material) or AdapterResult("authenticated", True)
        ),
        grant_resolver=gate,
        target_preflight=preflight,
        authorization_gate=gate,
    )

    result = coordinator.execute(_INTENT, fetch_credentials=lambda _: object())

    assert result.status == "not_shared"
    assert result.error_code == "grant_revoked"
    assert gate.entered == 1
    assert adapter_calls == []


def test_reassignment_after_final_recheck_is_rejected_inside_side_effect_gate() -> None:
    adapter_calls: list[object] = []
    authorization = _grant_resolver(_BINDING, "site-a", "target-a")
    gate = _AuthorizationGate(authorization)

    def reassign() -> None:
        gate.authorization = GrantAuthorization(
            username_ref="replacement-item",
            profile_id=authorization.profile_id,
            principal_id=authorization.principal_id,
            browser_id=authorization.browser_id,
            generation=authorization.generation,
            site_id=authorization.site_id,
            target_tab_id=authorization.target_tab_id,
            epoch=authorization.epoch + 1,
        )

    gate.before_authorize = reassign

    def preflight(intent, declaration):
        return "target-proof-v1"

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: _BINDING,
        resolve_pre_fill=lambda _: _BINDING,
        declarations={"site-a": _DECLARATION},
        adapter_selector=lambda *_: lambda declaration, material: (
            adapter_calls.append(material) or AdapterResult("authenticated", True)
        ),
        grant_resolver=gate,
        target_preflight=preflight,
        authorization_gate=gate,
    )

    result = coordinator.execute(_INTENT, fetch_credentials=lambda _: object())

    assert result.status == "failed"
    assert result.error_code == "grant_changed"
    assert gate.entered == 1
    assert adapter_calls == []
