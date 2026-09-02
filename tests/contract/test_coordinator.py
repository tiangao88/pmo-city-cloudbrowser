"""RED-stage tests for the deterministic broker coordinator.

- Coordinates resolution → declaration lookup → credential fetch → adapter
  execution while keeping the credential-bearing payload inside the closure
  and returning only a bounded BrokerResult.
- Re-resolves the server-side binding immediately before fill so owner /
  profile / browser / slot changes between fetch and fill invalidates work.
- Emits audit events for accepted / rejected, mfa_required, and completed
  outcomes; nothing else.

The coordinator's surface is intentionally generic over adapter selection
(``run_adapter``), so this test injects stub adapters and is allowed to
treat the adapter contract as a black box.
"""

from __future__ import annotations

from dataclasses import dataclass

from cloudbrowser.credential_broker import BrokerResult, LoginIntent
from cloudbrowser.credential_broker.audit import AuditEventType
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.service import AdapterResult, ResolvedBinding


@dataclass
class _Trace:
    """Minimal emission collector; the real emitter is exercised elsewhere."""

    events: list[tuple[AuditEventType, dict]]


class _StubAdapter:
    def __init__(self, payload: AdapterResult) -> None:
        self.payload = payload
        self.calls = 0

    def __call__(self, declaration, material) -> AdapterResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.payload


def make_intent(generation: str = "g1") -> LoginIntent:
    return LoginIntent(
        request_id="req-1",
        profile_id="profile-a",
        principal_id="alice@example.test",
        browser_id="browser-1",
        site_id="site-a",
        username_ref="acct-1",
        binding_generation=generation,
    )


def make_binding(generation: str = "g1", revoked: bool = False) -> ResolvedBinding:
    return ResolvedBinding(
        profile_id="profile-a",
        principal_id="alice@example.test",
        browser_id="browser-1",
        site_id="site-a",
        generation=generation,
        revoked=revoked,
    )


def test_coordinator_audits_accepted_login() -> None:
    trace = _Trace(events=[])
    adapter = _StubAdapter(AdapterResult("authenticated", True))
    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: make_binding(),
        resolve_pre_fill=lambda _: make_binding(),
        declarations={"site-a": _FakeDeclaration()},
        adapter_selector=lambda site, decl: adapter,
        audit_emit=lambda event_type, fields: trace.events.append((event_type, fields)),
    )

    result = coordinator.execute(make_intent(), fetch_credentials=lambda ref: object())
    assert result.status == "authenticated"
    assert adapter.calls == 1
    assert any(et == AuditEventType.BROKER_LOGIN for et, _ in trace.events)


def test_coordinator_re_runs_binding_resolution_pre_fill_and_rejects_change() -> None:
    trace = _Trace(events=[])
    adapter = _StubAdapter(AdapterResult("authenticated", True))
    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: make_binding(),
        resolve_pre_fill=lambda _: make_binding(generation="g2"),
        declarations={"site-a": _FakeDeclaration()},
        adapter_selector=lambda site, decl: adapter,
        audit_emit=lambda event_type, fields: trace.events.append((event_type, fields)),
    )

    result = coordinator.execute(make_intent(), fetch_credentials=lambda ref: object())
    assert result.status == "failed"
    assert result.error_code == "stale_binding"
    assert adapter.calls == 0
    assert any(et == AuditEventType.BROKER_LOGIN_FAILED for et, _ in trace.events)


def test_coordinator_emits_mfa_required_audit_when_adapter_returns_mfa() -> None:
    trace = _Trace(events=[])
    adapter = _StubAdapter(AdapterResult("mfa_required", False))
    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: make_binding(),
        resolve_pre_fill=lambda _: make_binding(),
        declarations={"site-a": _FakeDeclaration()},
        adapter_selector=lambda site, decl: adapter,
        audit_emit=lambda event_type, fields: trace.events.append((event_type, fields)),
    )

    result = coordinator.execute(make_intent(), fetch_credentials=lambda ref: object())
    assert result.status == "mfa_required"
    assert any(et == AuditEventType.BROKER_MFA_REQUESTED for et, _ in trace.events)


def test_coordinator_masks_credential_in_audit_fields() -> None:
    trace = _Trace(events=[])

    def emit(event_type, fields):
        # The audit transport must never receive the credential.
        for forbidden in ("username", "password"):
            assert forbidden not in fields, fields
        trace.events.append((event_type, fields))

    class _LeakyAdapter(_StubAdapter):
        def __init__(self) -> None:
            super().__init__(AdapterResult("authenticated", True))

        def __call__(self, declaration, material):  # type: ignore[no-untyped-def]
            self.calls += 1
            return AdapterResult("authenticated", identity_verified=True)

    adapter = _LeakyAdapter()
    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: make_binding(),
        resolve_pre_fill=lambda _: make_binding(),
        declarations={"site-a": _FakeDeclaration()},
        adapter_selector=lambda site, decl: adapter,
        audit_emit=emit,
    )

    coordinator.execute(make_intent(), fetch_credentials=lambda ref: object())
    # Should reach the adapter once, audit must not contain credentials.
    assert adapter.calls == 1


class _FakeDeclaration:
    """A duck-typed SiteDeclaration that allows the test's current URL only."""

    origin = "https://login.example.test"
    redirect_origins: tuple[str, ...] = ()

    def allows(self, current_url: str) -> bool:
        return current_url.startswith(self.origin)


def test_coordinator_returns_not_shared_when_credential_unavailable() -> None:
    adapter = _StubAdapter(AdapterResult("authenticated", True))
    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: make_binding(),
        resolve_pre_fill=lambda _: make_binding(),
        declarations={"site-a": _FakeDeclaration()},
        adapter_selector=lambda site, decl: adapter,
        audit_emit=lambda *_: None,
    )

    def fetch(ref):
        raise LookupError("no grant")

    result = coordinator.execute(make_intent(), fetch_credentials=fetch)
    assert result.status == "not_shared"
    assert result.error_code == "grant_unavailable"
    assert adapter.calls == 0
