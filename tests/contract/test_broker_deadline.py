"""Regression tests for the broker's shared monotonic deadline."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.credential_broker.adapters.basic import BasicAuthAdapter, BasicAuthDeclaration
from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.api import BrokerHttpServer, ServerIdentity
from cloudbrowser.credential_broker.contracts import GrantAuthorization
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.service import AdapterResult, ResolvedBinding
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability
from cloudbrowser.credential_broker.grant_custody import CustodyCredentialFetcher


_SECRET = b"deadline-capability-secret-0123456789"
_NOW = 10_000


def test_job_epoch_captured_before_idempotency_wait(tmp_path):
    from cloudbrowser.broker_jobs import BrokerJobs, JobsUnavailable
    from cloudbrowser.credential_broker.contracts import BrokerResult
    authority = BrokerJobs(tmp_path)
    authority.claim_authority()
    authority.change("agent")
    broker = BrokerJobs(tmp_path)
    calls = []
    class Coordinator:
        admission_epoch = broker.snapshot

        def execute(self, intent, *, fetch_credentials, deadline, admission_epoch):
            try:
                with broker.job(admission_epoch):
                    calls.append("fetch")
                    return BrokerResult(intent.request_id, "authenticated")
            except JobsUnavailable:
                return BrokerResult(intent.request_id, "failed", "browser_control_paused")
    class DelayedIdempotency:
        def execute(self, scope, operation, *, deadline):
            authority.change("human")
            authority.change("agent")
            return operation()
    try:
        server = _server(tmp_path, coordinator=Coordinator(), monotonic_clock=lambda: 0)
        server._idempotency_store = DelayedIdempotency()
        with server.handle("/v1/credential/login", {"capability": _token()}) as response:
            assert response.body["error_code"] == "browser_control_paused"
        assert calls == []
    finally:
        authority.close()


def test_http_admission_precedes_delayed_body(tmp_path):
    import http.client
    import json
    from threading import Event, Thread
    from cloudbrowser.broker_jobs import BrokerJobs, JobsUnavailable
    from cloudbrowser.credential_broker.contracts import BrokerResult
    from cloudbrowser.credential_broker.runtime import create_broker_http_server
    authority = BrokerJobs(tmp_path)
    authority.claim_authority()
    authority.change("agent")
    broker = BrokerJobs(tmp_path)
    entered = Event()
    calls = []
    class Coordinator:
        def admission_epoch(self):
            epoch = broker.snapshot()
            entered.set()
            return epoch

        def execute(self, intent, *, fetch_credentials, deadline, admission_epoch):
            try:
                with broker.job(admission_epoch):
                    calls.append("fetch")
                    return BrokerResult(intent.request_id, "authenticated")
            except JobsUnavailable:
                return BrokerResult(intent.request_id, "failed", "browser_control_paused")
    api = _server(tmp_path, coordinator=Coordinator(), monotonic_clock=lambda: 0)
    server = create_broker_http_server(api, ("127.0.0.1", 0))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    body = json.dumps({"capability": _token()}).encode()
    try:
        client.putrequest("POST", "/v1/credential/login")
        client.putheader("Content-Length", str(len(body)))
        client.endheaders()
        assert entered.wait(2)
        authority.change("human")
        authority.change("agent")
        client.send(body)
        response = client.getresponse()
        assert json.loads(response.read())["error_code"] == "browser_control_paused"
        assert calls == []
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(3)
        authority.close()


def _capability(**overrides: object) -> CredentialCapability:
    claims: dict[str, object] = {
        "profile_id": "profile-a",
        "principal_id": "principal-a",
        "browser_id": "browser-a",
        "generation": "generation-a",
        "site_id": "site-a",
        "target_tab_id": "target-a",
        "operation": "credential.login",
        "request_id": "request-a",
        "audience": "credential-broker",
        "deployment": "deployment-a",
        "issued_at": _NOW,
        "expires_at": _NOW + 5,
        "nonce": "deadline-nonce-a",
    }
    claims.update(overrides)
    return CredentialCapability(**claims)  # type: ignore[arg-type]


def _token(**overrides: object) -> str:
    return CapabilityCodec(_SECRET).encode(_capability(**overrides))


def _server(
    tmp_path: Path,
    *,
    coordinator: object,
    monotonic_clock,
    outer_timeout_s: float = 30.0,
) -> BrokerHttpServer:
    return BrokerHttpServer(
        server_identity=ServerIdentity("credential-broker", "deployment-a"),
        capability_codec=CapabilityCodec(_SECRET),
        capability_audience="credential-broker",
        deployment="deployment-a",
        nonce_store=DurableNonceStore(tmp_path / "nonces.sqlite3"),
        idempotency_store=DurableIdempotencyStore(tmp_path / "idempotency.sqlite3"),
        coordinator=coordinator,  # type: ignore[arg-type]
        fetch_credentials=lambda _ref: CredentialMaterial("alice", "pw"),
        clock=lambda: _NOW,
        monotonic_clock=monotonic_clock,
        outer_timeout_s=outer_timeout_s,
    )


def test_receiver_creates_one_monotonic_deadline_bounded_by_capability_expiry(
    tmp_path: Path,
) -> None:
    observed: list[BrokerDeadline] = []

    class Coordinator:
        def execute(self, intent, *, fetch_credentials, deadline):  # noqa: ANN001
            observed.append(deadline)
            return AdapterResult("authenticated", True)  # pragma: no cover

    # The coordinator is replaced below with a result-producing seam so this
    # test only asserts the absolute budget handed across the API boundary.
    class ResultCoordinator:
        def execute(self, intent, *, fetch_credentials, deadline):  # noqa: ANN001
            observed.append(deadline)
            from cloudbrowser.credential_broker.contracts import BrokerResult

            return BrokerResult(intent.request_id, "failed", "test")

    monotonic_values = iter((50.0, *([51.0] * 32)))
    server = _server(
        tmp_path,
        coordinator=ResultCoordinator(),
        monotonic_clock=lambda: next(monotonic_values),
        outer_timeout_s=30.0,
    )

    with server.handle("/v1/credential/login", {"capability": _token()}) as response:
        assert response.body["error_code"] == "test"

    assert len(observed) == 1
    assert observed[0].expires_at == pytest.approx(55.0)
    assert observed[0].remaining() == pytest.approx(4.0)


def test_receiver_rechecks_shared_deadline_before_consuming_nonce_or_running_work(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    class Coordinator:
        def execute(self, intent, *, fetch_credentials, deadline):  # noqa: ANN001
            calls.append("coordinator")
            raise AssertionError("expired request reached coordinator")

    monotonic_values = iter((50.0, 51.0, 51.0, 51.0, 51.0))
    server = _server(
        tmp_path,
        coordinator=Coordinator(),
        monotonic_clock=lambda: next(monotonic_values),
        outer_timeout_s=0.5,
    )

    with server.handle("/v1/credential/login", {"capability": _token()}) as response:
        body = dict(response.body)

    assert body["error_code"] == "deadline_exceeded"
    assert calls == []


def test_vault_transport_receives_remaining_shared_budget() -> None:
    observed: list[float] = []

    def transport(method, url, *, headers=None, body=None, timeout_s):  # noqa: ANN001
        observed.append(timeout_s)
        return 200, b"{}"

    clock_values = iter((100.0, 101.25))
    deadline = BrokerDeadline.from_receipt(
        receipt_monotonic=100.0,
        budget_s=5.0,
        monotonic_clock=lambda: 101.25,
    )
    client = CustodyCredentialFetcher.__new__(CustodyCredentialFetcher)
    client._transport = transport
    client._base_url = "https://vault.example.test"

    client._call("GET", "/api/sync", deadline=deadline)

    assert observed == [pytest.approx(3.75)]


def test_basic_auth_refuses_credential_side_effect_after_deadline() -> None:
    class ExpiredDeadline:
        def check(self) -> float:
            raise BrokerDeadlineExceeded("expired")

    class Browser:
        def current_url(self, *, target_id: str) -> str:
            return "https://basic.example.test/protected"

        def submit_basic_auth(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("credentials must not be submitted after expiry")

        def application_authenticated(self, *, target_id: str) -> bool:
            return False

    declaration = BasicAuthDeclaration(
        site_id="site-a",
        origin="https://basic.example.test",
        success_path="/home",
    )

    with pytest.raises(BrokerDeadlineExceeded):
        BasicAuthAdapter().execute(
            declaration,
            CredentialMaterial("alice", "pw"),
            Browser(),
            target_id="target-a",
            deadline=ExpiredDeadline(),
        )


def test_coordinator_passes_one_deadline_to_preflight_fetch_and_adapter() -> None:
    phases: list[tuple[str, object]] = []
    binding = ResolvedBinding("profile-a", "principal-a", "browser-a", "site-a", "generation-a")

    class Grant:
        username_ref = "server-item"

        def __eq__(self, other):  # noqa: ANN001
            return other is self

    grant = Grant()

    class Deadline:
        def check(self):
            return 10.0

    class Gate:
        def run_authorized(self, authorization, operation, *, deadline):  # noqa: ANN001
            return operation(CredentialMaterial("alice", "pw"))

    deadline = Deadline()
    coordinator = BrokerCoordinator(
        resolve_initial=lambda intent: binding,
        resolve_pre_fill=lambda intent: binding,
        declarations={"site-a": type("Declaration", (), {"site_id": "site-a"})()},
        adapter_selector=lambda site, declaration, intent, *, deadline: (
            lambda declaration, material, *, deadline: phases.append(("adapter", deadline))
            or AdapterResult("authenticated", True)
        ),
        grant_resolver=lambda binding, site_id, target_tab_id: GrantAuthorization(
            username_ref="server-item",
            profile_id=binding.profile_id,
            principal_id=binding.principal_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
            site_id=site_id,
            target_tab_id=target_tab_id,
        ),
        target_preflight=lambda intent, declaration, *, deadline: phases.append(
            ("preflight", deadline)
        ) or "target",
        authorization_gate=Gate(),
    )

    result = coordinator.execute(
        type(
            "Intent",
            (),
            {
                "request_id": "request-a",
                "profile_id": "profile-a",
                "principal_id": "principal-a",
                "browser_id": "browser-a",
                "site_id": "site-a",
                "target_tab_id": "target-a",
                "binding_generation": "generation-a",
                "username_ref": "server-item",
            },
        )(),
        fetch_credentials=lambda ref, *, deadline: phases.append(("fetch", deadline))
        or CredentialMaterial("alice", "pw"),
        deadline=deadline,
    )

    assert result.status == "authenticated"
    assert [phase for phase, _ in phases] == ["preflight", "fetch", "preflight", "adapter"]
    assert all(value is deadline for _, value in phases)
