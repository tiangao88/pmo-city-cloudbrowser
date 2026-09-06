"""RED tests: router → agent-control forwarding client (§3.1).

``AgentControlForwarder`` mirrors ``SupervisorClient``: it resolves a
``slot_id`` to a private agent-control base URL from a server-supplied map,
never from network input, and relays a bounded JSON envelope to
``POST /agent-control/v1`` on that slot's agent-control service.

Security contract tested here:

- The trusted secret is required and validated locally (≥16 printable chars).
- The server derives the binding (principal/browser/generation) from the
  session; the caller can never supply one.
- The forwarder never forwards caller ``Remote-*`` headers: the binding
  arrives only via the allowlisted ``X-CB-*`` headers.
- Base URLs must be HTTP(S) origins without userinfo/query/fragment; the
  URL path may only be a simple absolute prefix.
- Failures surface as typed errors (``AgentControlForwarderError`` for
  locally refused arguments, ``AgentControlUnavailable`` for unreachable or
  unusable endpoints) — never raw exception text.
- Responses are bounded; oversized or non-object responses are unusable.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.browser_slots import BrowserBinding
from cloudbrowser.router.agent_control_forwarder import (
    AgentControlForwarder,
    AgentControlForwarderError,
    AgentControlUnavailable,
)


_SECRET = "router-agent-shared-secret-0123456789"
_BINDING = BrowserBinding(
    principal_id="pmo-owner",
    profile_id="profile-pmo-owner",
    browser_id="browser-1",
    generation="generation-q-abc123",
)


class _RecordingAgentControl(BaseHTTPRequestHandler):
    """Stand-in agent-control endpoint that records what actually arrives."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
        assert self.path == "/agent-control/v1", self.path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        type(self).last_request = {
            "path": self.path,
            "secret": self.headers.get("X-CB-Trusted-Secret"),
            "principal": self.headers.get("X-CB-Principal"),
            "browser": self.headers.get("X-CB-Browser"),
            "generation": self.headers.get("X-CB-Generation"),
            "remote_email": self.headers.get("Remote-Email"),
            "remote_user": self.headers.get("Remote-User"),
            "body": json.loads(raw.decode("utf-8")) if raw else None,
        }
        body = json.dumps(
            {"request_id": "req-1", "status": "ok", "page": {"url": "https://example.test", "title": "Example", "text": "Hello"}}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _start(server: ThreadingHTTPServer) -> str:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def _forwarder(**overrides: object) -> AgentControlForwarder:
    kwargs: dict[str, object] = {
        "slot_urls": {"slot-1": "http://agent-1:8090", "slot-2": "http://agent-2:8090"},
        "trusted_secret": _SECRET,
    }
    kwargs.update(overrides)
    return AgentControlForwarder(**kwargs)  # type: ignore[arg-type]


def test_forwarder_posts_bounded_envelope_with_server_derived_binding_headers() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingAgentControl)
    base_url = _start(server)
    try:
        forwarder = AgentControlForwarder(
            slot_urls={"slot-1": base_url},
            trusted_secret=_SECRET,
        )
        result = forwarder.forward(
            "slot-1",
            binding=_BINDING,
            operation="page_info",
            params={},
            request_id="req-1",
        )
        assert result["status"] == "ok"
        sent = _RecordingAgentControl.last_request
        assert sent["path"] == "/agent-control/v1"
        assert sent["secret"] == _SECRET
        assert sent["principal"] == "pmo-owner"
        assert sent["browser"] == "browser-1"
        assert sent["generation"] == "generation-q-abc123"
        assert sent["body"] == {"request_id": "req-1", "operation": "page_info", "params": {}}
        # Caller Remote-* headers are never part of the relay contract.
        assert sent["remote_email"] is None
        assert sent["remote_user"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_forwarder_validates_inputs_locally_and_fails_typed() -> None:
    forwarder = _forwarder()
    with pytest.raises(AgentControlForwarderError):
        forwarder.forward(
            "slot-unknown",
            binding=_BINDING,
            operation="page_info",
            params={},
            request_id="req-1",
        )
    with pytest.raises(AgentControlForwarderError):
        forwarder.forward(
            "slot-1",
            binding=_BINDING,
            operation="raw_cdp",
            params={},
            request_id="req-1",
        )
    with pytest.raises(AgentControlForwarderError):
        forwarder.forward(
            "slot-1",
            binding=_BINDING,
            operation="page_info",
            params={},
            request_id="",
        )
    with pytest.raises(AgentControlForwarderError):
        forwarder.forward(
            "slot-1",
            binding="not-a-binding",  # type: ignore[arg-type]
            operation="page_info",
            params={},
            request_id="req-1",
        )


def test_forwarder_requires_strong_trusted_secret_and_clean_urls() -> None:
    with pytest.raises(ValueError):
        _forwarder(trusted_secret="short")
    with pytest.raises(ValueError):
        _forwarder(trusted_secret="has\ncontrol\r\nchars012345")
    with pytest.raises(ValueError):
        _forwarder(slot_urls={"slot-1": "http://user:pass@agent-1:8090"})
    with pytest.raises(ValueError):
        _forwarder(slot_urls={"slot-1": "ftp://agent-1:8090"})
    with pytest.raises(ValueError):
        _forwarder(slot_urls={"slot-1": "http://agent-1:8090/path?query=1"})
    with pytest.raises(ValueError):
        _forwarder(slot_urls={})
    with pytest.raises(ValueError):
        _forwarder(slot_urls={"bad slot!": "http://agent-1:8090"})


def test_forwarder_surfaces_unreachable_endpoints_as_unavailable() -> None:
    # Port 1 on localhost is never serving; connection must fail as
    # AgentControlUnavailable, not as a raw OSError.
    forwarder = AgentControlForwarder(
        slot_urls={"slot-1": "http://127.0.0.1:1"},
        trusted_secret=_SECRET,
        timeout_s=0.5,
    )
    with pytest.raises(AgentControlUnavailable):
        forwarder.forward(
            "slot-1",
            binding=_BINDING,
            operation="page_info",
            params={},
            request_id="req-1",
        )


def test_forwarder_rejects_oversized_and_non_object_responses() -> None:
    captured: dict[str, object] = {}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if captured.get("mode") == "oversize":
                self.send_response(200)
                self.send_header("Content-Length", "100000")
                self.end_headers()
                self.wfile.write(b"x" * 100000)
                return
            if captured.get("mode") == "nonobject":
                body = b"[1,2,3]"
            else:
                body = b"not json"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    base_url = _start(server)
    try:
        forwarder = AgentControlForwarder(
            slot_urls={"slot-1": base_url},
            trusted_secret=_SECRET,
            timeout_s=2.0,
        )
        for mode in ("garbage", "nonobject", "oversize"):
            captured["mode"] = mode
            with pytest.raises(AgentControlUnavailable):
                forwarder.forward(
                    "slot-1",
                    binding=_BINDING,
                    operation="page_info",
                    params={},
                    request_id="req-1",
                )
    finally:
        server.shutdown()
        server.server_close()


def test_forwarder_relays_server_http_status_ok_only() -> None:
    """401/404/5xx from agent-control must surface as unavailable/typed errors,
    never silently as success envelopes."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    base_url = _start(server)
    try:
        forwarder = AgentControlForwarder(
            slot_urls={"slot-1": base_url},
            trusted_secret=_SECRET,
            timeout_s=2.0,
        )
        with pytest.raises(AgentControlUnavailable):
            forwarder.forward(
                "slot-1",
                binding=_BINDING,
                operation="page_info",
                params={},
                request_id="req-1",
            )
    finally:
        server.shutdown()
        server.server_close()


def test_forwarder_known_slots_is_frozen() -> None:
    forwarder = _forwarder()
    assert forwarder.known_slots == frozenset({"slot-1", "slot-2"})
