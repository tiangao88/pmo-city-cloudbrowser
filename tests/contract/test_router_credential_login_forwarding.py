"""RED tests for router/viewer credential-login forwarding."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

import pytest

from cloudbrowser.browser_slots import BrowserBinding
from cloudbrowser.credential_capability import CapabilityCodec
from cloudbrowser.router.credential_broker_forwarder import (
    CredentialBrokerForwarder,
    CredentialBrokerUnavailable,
)
from cloudbrowser.router.router_api import RouterApi, create_router_server
from cloudbrowser.router.sessions import RouterSessionStore, SessionStatus, SlotDescriptor
from cloudbrowser.viewer import create_viewer_server
from cloudbrowser.viewer.session_surface import RouterHttpClient, ViewerSessionSurface


_SECRET = b"router-broker-capability-secret-0123456789"
_IDENTITY_HEADERS = {
    "Remote-Sub": "sub-1",
    "Remote-Groups": "PMOC_Users",
    "Remote-Email": "owner@example.test",
}


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Identity:
    def resolve(self, identity: object) -> str | None:
        return "principal-owner"


class _Supervisor:
    known_slots = frozenset({"slot-1"})

    def post_control(self, slot_id: str, *, operation: str, request_id: str):
        raise AssertionError("credential login must not wake a slot")


class _RecordingBroker:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def forward(self, capability: str, *, request_id: str) -> dict[str, object]:
        self.tokens.append(capability)
        return {
            "request_id": request_id,
            "status": "authenticated",
            "error_code": None,
            "duration_ms": 12,
        }


def _api(tmp_path: Path) -> tuple[RouterApi, _RecordingBroker, CapabilityCodec, _Clock]:
    clock = _Clock()
    store = RouterSessionStore(
        tmp_path / "router.json",
        slots=(SlotDescriptor("slot-1", "http://supervisor:8081", "browser-1"),),
        clock=clock,
    )
    session = store.enqueue("principal-owner", request_id="join-1")
    assert session.binding is not None
    assert store.activate(session.session_id).status is SessionStatus.ACTIVE
    broker = _RecordingBroker()
    codec = CapabilityCodec(_SECRET)
    return (
        RouterApi(
            session_store=store,
            supervisor_client=_Supervisor(),
            identity_client=_Identity(),  # type: ignore[arg-type]
            credential_broker_forwarder=broker,  # type: ignore[arg-type]
            capability_codec=codec,
            capability_audience="credential-broker",
            deployment="deployment-a",
            capability_ttl_s=30,
            clock=clock,
            nonce_factory=lambda: "nonce-router-1",
        ),
        broker,
        codec,
        clock,
    )


def test_router_mints_signed_capability_from_active_session_only(tmp_path: Path) -> None:
    api, broker, codec, _clock = _api(tmp_path)

    status, payload = api.credential_login(
        headers=_IDENTITY_HEADERS,
        body={
            "request_id": "login-1",
            "site_id": "site-a",
            "target_tab_id": "tab-1",
        },
    )

    assert status == 200
    assert payload == {
        "request_id": "login-1",
        "status": "authenticated",
        "error_code": None,
        "duration_ms": 12,
    }
    assert len(broker.tokens) == 1
    claims = codec.decode(
        broker.tokens[0],
        now=1001,
        audience="credential-broker",
        deployment="deployment-a",
        operation="credential.login",
    )
    assert claims.profile_id == "profile-principal-owner"
    assert claims.principal_id == "principal-owner"
    assert claims.browser_id == "browser-1"
    assert claims.generation.startswith("generation-q-")
    assert claims.site_id == "site-a"
    assert claims.target_tab_id == "tab-1"
    assert claims.request_id == "login-1"
    assert claims.nonce == "nonce-router-1"
    assert "capability" not in json.dumps(payload)


def test_router_rejects_caller_credential_references_before_forwarding(tmp_path: Path) -> None:
    api, broker, _codec, _clock = _api(tmp_path)

    for field in ("username_ref", "grant_ref"):
        status, payload = api.credential_login(
            headers=_IDENTITY_HEADERS,
            body={
                "request_id": "login-1",
                "site_id": "site-a",
                "target_tab_id": "tab-1",
                field: "caller-selected-secret-reference",
            },
        )
        assert status == 200
        assert payload["error_code"] == "invalid_request"
    assert broker.tokens == []


def test_router_rejects_oversized_request_id_without_echoing_it(tmp_path: Path) -> None:
    api, broker, _codec, _clock = _api(tmp_path)
    oversized_request_id = "attacker-controlled-" + ("x" * 512)

    status, payload = api.credential_login(
        headers=_IDENTITY_HEADERS,
        body={
            "request_id": oversized_request_id,
            "site_id": "site-a",
            "target_tab_id": "tab-1",
        },
    )

    assert status == 200
    assert payload == {
        "request_id": "",
        "status": "failed",
        "error_code": "invalid_request",
    }
    assert oversized_request_id not in json.dumps(payload)
    assert broker.tokens == []


def test_router_http_route_returns_status_only(tmp_path: Path) -> None:
    api, _broker, _codec, _clock = _api(tmp_path)
    server = create_router_server(api, address=("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request(
            "POST",
            "/v1/credential/login",
            body=json.dumps(
                {"request_id": "login-http", "site_id": "site-a", "target_tab_id": "tab-1"}
            ).encode(),
            headers={**_IDENTITY_HEADERS, "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        assert response.status == 200
        assert set(body) == {"request_id", "status", "error_code", "duration_ms"}
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


class _BrokerHandler(BaseHTTPRequestHandler):
    body: dict[str, object] | None = None
    headers_seen: dict[str, str] = {}

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        assert self.path == "/v1/credential/login"
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        type(self).body = json.loads(raw)
        type(self).headers_seen = {key.lower(): value for key, value in self.headers.items()}
        payload = json.dumps(
            {
                "request_id": "login-1",
                "status": "mfa_required",
                "error_code": "mfa_required",
                "duration_ms": 3,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_broker_forwarder_sends_only_opaque_capability(tmp_path: Path) -> None:
    del tmp_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BrokerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        forwarder = CredentialBrokerForwarder(
            f"http://127.0.0.1:{server.server_address[1]}"
        )
        result = forwarder.forward("opaque.signed.capability", request_id="login-1")
        assert result["status"] == "mfa_required"
        assert _BrokerHandler.body == {"capability": "opaque.signed.capability"}
        assert "authorization" not in _BrokerHandler.headers_seen
        assert "x-cb-broker-secret" not in _BrokerHandler.headers_seen
        assert "username_ref" not in json.dumps(_BrokerHandler.body)
        assert "grant_ref" not in json.dumps(_BrokerHandler.body)
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_broker_forwarder_rejects_response_for_different_request_id(monkeypatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b'{"request_id":"broker-other","status":"failed","error_code":"credential_rejected"}'

    monkeypatch.setattr(
        "cloudbrowser.router.credential_broker_forwarder.urlopen",
        lambda request, *, timeout: Response(),
    )
    forwarder = CredentialBrokerForwarder(
        "http://credential-broker:8084", timeout_s=1.0, capability_ttl_s=2
    )

    with pytest.raises(CredentialBrokerUnavailable, match="request id"):
        forwarder.forward("opaque.signed.capability", request_id="router-request")


def test_broker_forwarder_default_deadline_covers_default_authentik_stage() -> None:
    forwarder = CredentialBrokerForwarder("http://credential-broker:8084")
    assert forwarder.timeout_s == 25.0


def test_broker_forwarder_rejects_deadline_at_capability_expiry() -> None:
    with pytest.raises(ValueError, match="capability TTL"):
        CredentialBrokerForwarder(
            "http://credential-broker:8084", timeout_s=30.0, capability_ttl_s=30
        )


def test_broker_forwarder_rejects_deadline_beyond_capability_ttl() -> None:
    with pytest.raises(ValueError, match="capability TTL"):
        CredentialBrokerForwarder(
            "http://credential-broker:8084", timeout_s=30.0, capability_ttl_s=29
        )


def test_forwarder_uses_one_total_deadline_for_transport(monkeypatch) -> None:
    clock = iter((100.0, 100.4, 100.4, 100.4, 100.4, 100.4, 100.4))
    timeouts = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            assert size == 16 * 1024 + 1
            return b'{"request_id":"login-1","status":"failed","error_code":"credential_rejected"}'

    def fake_urlopen(request, *, timeout):
        timeouts.append(timeout)
        return Response()

    monkeypatch.setattr(
        "cloudbrowser.router.credential_broker_forwarder.time.monotonic",
        lambda: next(clock),
    )
    monkeypatch.setattr(
        "cloudbrowser.router.credential_broker_forwarder.urlopen", fake_urlopen
    )
    forwarder = CredentialBrokerForwarder(
        "http://credential-broker:8084", timeout_s=1.0, capability_ttl_s=2
    )

    result = forwarder.forward("opaque.signed.capability", request_id="login-1")
    assert result["status"] == "failed"
    assert result["error_code"] == "credential_rejected"
    assert timeouts == [pytest.approx(0.6)]


def test_forwarder_aborts_body_stream_after_absolute_deadline(monkeypatch) -> None:
    clock = iter((100.0, 100.0, 100.7))

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            next(clock)
            return b'{"request_id":"login-1","status":"failed","error_code":"credential_rejected"}'

    monkeypatch.setattr(
        "cloudbrowser.router.credential_broker_forwarder.time.monotonic",
        lambda: next(clock),
    )
    monkeypatch.setattr(
        "cloudbrowser.router.credential_broker_forwarder.urlopen",
        lambda request, *, timeout: Response(),
    )
    forwarder = CredentialBrokerForwarder(
        "http://credential-broker:8084", timeout_s=0.5, capability_ttl_s=2
    )

    with pytest.raises(CredentialBrokerUnavailable, match="deadline"):
        forwarder.forward("opaque.signed.capability", request_id="login-1")


def test_forwarder_rejects_non_success_http_with_invalid_body(monkeypatch) -> None:
    def fake_urlopen(request, *, timeout):
        raise HTTPError(
            request.full_url,
            502,
            "bad gateway",
            Message(),
            BytesIO(b"upstream failure"),
        )

    monkeypatch.setattr(
        "cloudbrowser.router.credential_broker_forwarder.urlopen", fake_urlopen
    )
    forwarder = CredentialBrokerForwarder(
        "http://credential-broker:8084", timeout_s=1.0, capability_ttl_s=2
    )

    with pytest.raises(CredentialBrokerUnavailable):
        forwarder.forward("opaque.signed.capability", request_id="login-1")


def test_broker_forwarder_rejects_unavailable_dependency() -> None:
    forwarder = CredentialBrokerForwarder("http://127.0.0.1:1", timeout_s=0.2)
    with pytest.raises(CredentialBrokerUnavailable):
        forwarder.forward("opaque.signed.capability", request_id="login-1")


class _ViewerRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def credential_login(self, *, headers, site_id, target_tab_id, request_id):  # noqa: ANN001
        self.calls.append(
            {
                "headers": dict(headers),
                "site_id": site_id,
                "target_tab_id": target_tab_id,
                "request_id": request_id,
            }
        )
        return 200, {
            "request_id": request_id,
            "status": "authenticated",
            "error_code": None,
            "duration_ms": 4,
        }


def test_viewer_surface_forwards_intent_without_credential_references() -> None:
    router = _ViewerRouter()
    surface = ViewerSessionSurface(identity_client=_Identity(), router_api=router)  # type: ignore[arg-type]

    status, payload = surface.credential_login(
        headers=_IDENTITY_HEADERS,
        site_id="site-a",
        target_tab_id="tab-1",
        request_id="viewer-login-1",
    )

    assert status == 200
    assert payload["status"] == "authenticated"
    assert router.calls == [
        {
            "headers": {"remote-sub": "sub-1", "remote-groups": "PMOC_Users", "remote-email": "owner@example.test"},
            "site_id": "site-a",
            "target_tab_id": "tab-1",
            "request_id": "viewer-login-1",
        }
    ]


def test_viewer_http_route_accepts_only_bounded_login_intent() -> None:
    router = _ViewerRouter()
    surface = ViewerSessionSurface(identity_client=_Identity(), router_api=router)  # type: ignore[arg-type]
    server = create_viewer_server(
        None,
        address=("127.0.0.1", 0),
        allow_edge_identity=True,
        session_surface=surface,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request(
            "POST",
            "/ui/credential/login",
            body=json.dumps(
                {
                    "request_id": "viewer-http-1",
                    "site_id": "site-a",
                    "target_tab_id": "tab-1",
                }
            ).encode(),
            headers={**_IDENTITY_HEADERS, "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        assert response.status == 200
        assert body["status"] == "authenticated"
        assert router.calls[0]["request_id"] == "viewer-http-1"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_compose_wires_router_capability_secret_and_broker_url() -> None:
    root = Path(__file__).resolve().parents[2]
    for filename in ("compose.yaml", "compose.coolify.yaml"):
        text = (root / "deploy" / "coolify" / filename).read_text(encoding="utf-8")
        router = text.split("  router:", 1)[1].split("  slot-supervisor:", 1)[0]
        assert "CB_CREDENTIAL_BROKER_URL:" in router
        assert "CB_CREDENTIAL_CAPABILITY_SECRET:" in router
        assert "CB_CREDENTIAL_BROKER_AUDIENCE:" in router
