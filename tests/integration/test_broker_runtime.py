"""Runtime wiring tests for the credential broker (Layer 3).

Exercises the full stack: env-configured BrokerHttpServer over a real
stdlib HTTP server, with a fake refresh/session Vaultwarden transport on the
other side. Proves end-to-end that only status reaches the caller and
per-user wrapped custody material never leaves the process.

The request-time live-binding regression is covered in
``tests/contract/test_broker_dynamic_binding.py``; this file retains the
broader Vaultwarden transport coverage.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cloudbrowser.credential_broker.grant_custody import CustodyGrantStore, GrantScope
from cloudbrowser.credential_broker.runtime import create_broker_server, make_urllib_transport
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability

GRANT_KEK = bytes.fromhex("11" * 32)
VAULT_KEY = hashlib.sha256(b"user-sym-key").digest() + hashlib.sha256(
    b"user-mac-key"
).digest()
REFRESH_TOKEN = "grant-refresh-token"
ROTATED_REFRESH_TOKEN = "rotated-grant-refresh-token"


class FakeBrowserHandler(BaseHTTPRequestHandler):
    """Expose only the live binding and exact target needed by the broker."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/browser/readiness":
            self._json(
                {
                    "profile_id": "profile-a",
                    "owner": "alice@example.test",
                    "browser_id": "browser-1",
                    "generation": "g1",
                    "cdp_ok": True,
                }
            )
            return
        if self.path == "/agent/pages":
            self._json(
                {
                    "pages": [
                        {
                            "tab_id": "target-1",
                            "url": "https://example.test/login",
                            "title": "Login",
                        }
                    ]
                }
            )
            return
        self.send_response(404)
        self.end_headers()


class FakeVaultHandler(BaseHTTPRequestHandler):
    """Replay refresh-token login plus a Vaultwarden sync response."""

    server_version = "FakeVault/1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/identity/connect/token":
            self._send_token(raw)
            return
        self.send_response(404)
        self.end_headers()

    def _send_token(self, raw: bytes) -> None:
        from urllib.parse import parse_qs

        form = parse_qs(raw.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] in ([REFRESH_TOKEN], [ROTATED_REFRESH_TOKEN])
        assert "username" not in form
        assert "password" not in form
        self._json(
            200,
            {
                "access_token": "live-access-token",
                "refresh_token": ROTATED_REFRESH_TOKEN,
                "token_type": "Bearer",
                "expires_in": 300,
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/sync":
            self._send_sync()
            return
        self.send_response(404)
        self.end_headers()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sync(self) -> None:
        assert self.headers.get("Authorization", "") == "Bearer live-access-token"
        base = self.server  # type: ignore[attr-defined]
        self._json(200, {"ciphers": base.ciphers})  # type: ignore[attr-defined]


@pytest.fixture()
def fake_vault():
    handler = type("Handler", (FakeVaultHandler,), {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    user_key = VAULT_KEY

    def enc_string(plaintext: str, key64: bytes) -> str:
        import base64
        import hmac as hmac_mod

        from cloudbrowser.security import vault_crypto as crypto2

        if hasattr(crypto2, "stretch_to_enc_mac"):
            e, m = crypto2.stretch_to_enc_mac(key64)
        else:
            e, m = None, None
        iv = os.urandom(16)
        ct = crypto2.aes_cbc_encrypt(e or key64[:32], iv, plaintext.encode())
        mac = hmac_mod.new(m or key64[32:], iv + ct, hashlib.sha256).digest()
        return "2.{}|{}|{}".format(
            base64.b64encode(iv).decode(),
            base64.b64encode(ct).decode(),
            base64.b64encode(mac).decode(),
        )

    server.ciphers = [  # type: ignore[attr-defined]
        {
            "id": "item-1",
            "organizationId": None,
            "type": 1,
            "name": enc_string("PMO Test Site", user_key),
            "login": {
                "username": enc_string("alice@example.test", user_key),
                "password": enc_string("s3cret-pw", user_key),
                "totp": None,
                "uris": [{"uri": enc_string("https://example.test/", user_key)}],
            },
        }
    ]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def live_browser(monkeypatch):
    handler = type("BrowserHandler", (FakeBrowserHandler,), {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("CB_BROWSER_API_URL", f"http://127.0.0.1:{server.server_address[1]}")
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture()
def broker_env(monkeypatch, fake_vault, tmp_path):
    monkeypatch.setenv("CB_INSTANCE_ID", "test-broker")
    monkeypatch.setenv("CB_RELEASE_VERSION", "vtest")
    monkeypatch.setenv("CB_PROFILE_ID", "profile-a")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "alice@example.test")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-1")
    monkeypatch.setenv("CB_BINDING_GENERATION", "g1")
    monkeypatch.setenv("CB_CREDENTIAL_CAPABILITY_SECRET", "capability-secret-0123456789")
    monkeypatch.setenv("CB_CREDENTIAL_BROKER_AUDIENCE", "credential-broker")
    monkeypatch.setenv(
        "CB_BROKER_GRANT_DB_PATH", str(tmp_path / "grant-custody-v1.sqlite3")
    )
    monkeypatch.setenv("CB_BROKER_IDEMPOTENCY_DB_PATH", str(tmp_path / "idempotency.sqlite3"))
    monkeypatch.setenv("CB_CREDENTIAL_NONCE_DB_PATH", str(tmp_path / "nonces.sqlite3"))
    monkeypatch.setenv("CB_BROKER_SUBMIT_SECRET", "submit-secret-0123456789abcdef")
    monkeypatch.setenv("CB_BROKER_ADAPTER", "basic")
    monkeypatch.setenv("CB_BROKER_SITE_ID", "site-a")
    monkeypatch.setenv("CB_BROKER_ORIGIN", "https://example.test")
    monkeypatch.setenv("CB_BROKER_SUCCESS_PATH", "/authenticated")
    monkeypatch.setenv("CB_BROKER_USERNAME_SELECTOR", "#username")
    monkeypatch.setenv("CB_BROKER_PASSWORD_SELECTOR", "#password")
    monkeypatch.setenv("CB_BROKER_SUBMIT_SELECTOR", "#submit")
    monkeypatch.setenv("CB_BROKER_SUCCESS_SELECTOR", ".welcome")
    monkeypatch.setenv("CB_VAULT_BASE_URL", f"http://127.0.0.1:{fake_vault.server_address[1]}")
    monkeypatch.setenv("CB_BROKER_GRANT_KEK_HEX", GRANT_KEK.hex())
    monkeypatch.delenv("CB_VAULT_EMAIL", raising=False)
    monkeypatch.delenv("CB_VAULT_PASSWORD", raising=False)
    grants = CustodyGrantStore(tmp_path / "grant-custody-v1.sqlite3", kek=GRANT_KEK)
    grants.provision(
        scope=GrantScope(
            profile_id="profile-a",
            principal_id="alice@example.test",
            site_id="site-a",
            target_tab_id="target-1",
            browser_id="browser-1",
            generation="g1",
        ),
        item_ref="item-1",
        vault_key=VAULT_KEY,
        refresh_token=REFRESH_TOKEN.encode(),
        operator_id="integration-test",
    )


@pytest.fixture()
def broker_server(broker_env):
    server = create_broker_server(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _capability_payload(request_id: str, nonce: str) -> dict[str, str]:
    now = int(time.time())
    capability = CredentialCapability(
        profile_id="profile-a",
        principal_id="alice@example.test",
        browser_id="browser-1",
        generation="g1",
        site_id="site-a",
        target_tab_id="target-1",
        operation="credential.login",
        request_id=request_id,
        audience="credential-broker",
        deployment="test-broker",
        issued_at=now,
        expires_at=now + 30,
        nonce=nonce,
    )
    return {"capability": CapabilityCodec("capability-secret-0123456789").encode(capability)}


def _post_login(port: int, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/credential/login",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _post_raw(port: int, body: bytes) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/credential/login",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_full_stack_status_only_response(broker_server) -> None:
    port = broker_server.server_address[1]
    status, body = _post_login(
        port,
        _capability_payload("req-live-1", "nonce-live-1"),
    )
    assert status == 200
    assert body == {
        "request_id": "req-live-1",
        "status": "failed",
        "error_code": "browser_unavailable",
        "duration_ms": 0,
    }
    assert "s3cret-pw" not in json.dumps(body)
    assert "alice@example.test" not in json.dumps(body)


def test_full_stack_rejects_invalid_capability(broker_server) -> None:
    port = broker_server.server_address[1]
    status, body = _post_login(port, {"capability": "not-a-valid-capability"})
    assert status == 200
    assert body["status"] == "failed"
    assert body["error_code"] == "invalid_capability"


def test_full_stack_malformed_json_is_status_only_http_200(broker_server) -> None:
    status, body = _post_raw(broker_server.server_address[1], b"{")
    assert status == 200
    assert body == {
        "request_id": "missing",
        "status": "failed",
        "error_code": "invalid_request",
        "duration_ms": 0,
    }


def test_full_stack_rejects_legacy_auth_token_and_username_ref_schema(broker_server) -> None:
    port = broker_server.server_address[1]
    status, body = _post_login(
        port,
        {
            "auth_token": "broker-secret-0123456789abcdef",
            "username_ref": "caller-selected-item",
        },
    )
    assert status == 200
    assert body == {
        "request_id": "missing",
        "status": "failed",
        "error_code": "invalid_request",
        "duration_ms": 0,
    }


def test_full_stack_server_owned_unknown_grant_ref_fails_closed(
    broker_env, live_browser, monkeypatch, fake_vault, tmp_path
) -> None:
    monkeypatch.setenv(
        "CB_BROKER_GRANT_DB_PATH", str(tmp_path / "unknown" / "grant-custody-v1.sqlite3")
    )
    server = create_broker_server(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_login(
            server.server_address[1],
            _capability_payload("req-live-3", "nonce-live-3"),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status == 200
    assert body == {
        "request_id": "req-live-3",
        "status": "not_shared",
        "error_code": "grant_unavailable",
        "duration_ms": 0,
    }
    assert "no-such-item" not in json.dumps(body)


def test_full_stack_unavailable_vault_is_status_only_http_200(
    broker_env, live_browser, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CB_VAULT_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CB_CREDENTIAL_NONCE_DB_PATH", str(tmp_path / "vault-down-nonces.sqlite3"))
    server = create_broker_server(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_login(
            server.server_address[1],
            _capability_payload("req-live-4", "nonce-live-4"),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status == 200
    assert body == {
        "request_id": "req-live-4",
        "status": "failed",
        "error_code": "dependency_unavailable",
        "duration_ms": 0,
    }


def test_transport_refuses_foreign_host() -> None:
    transport = make_urllib_transport("http://vault.internal")
    with pytest.raises(ValueError):
        transport("GET", "http://evil.example/api/sync")


def test_health_endpoint(broker_server) -> None:
    port = broker_server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        doc = json.loads(response.read().decode())
    assert doc == {"status": "ok", "component": "credential-broker"}
