"""Runtime wiring tests for the credential broker (Layer 3).

Exercises the full stack: env-configured BrokerHttpServer over a real
stdlib HTTP server, with a fake Vaultwarden on the other side. Proves
end-to-end that only status reaches the caller and the vault password
never leaves the process.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cloudbrowser.credential_broker.runtime import create_broker_server, make_urllib_transport

EMAIL = "broker-test@aikumi.pro"
PASSWORD = "correct horse battery staple"
ITERATIONS = 600_000


class FakeVaultHandler(BaseHTTPRequestHandler):
    """Replays a Vaultwarden; records calls; validates nothing else."""

    server_version = "FakeVault/1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _kdf_payload(self) -> dict:
        return getattr(self.server, "kdf_payload", {"kdf": 0, "kdfIterations": ITERATIONS})  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/api/accounts/prelogin":
            self._send_prelogin(raw)
            return
        if self.path == "/identity/connect/token":
            self._send_token(raw)
            return
        self.send_response(404)
        self.end_headers()

    def _send_prelogin(self, raw: bytes) -> None:
        doc = json.loads(raw.decode())
        assert doc["email"] == EMAIL
        self.send_response(200)
        body = json.dumps(self._kdf_payload()).encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_token(self, raw: bytes) -> None:
        from urllib.parse import parse_qs

        form = parse_qs(raw.decode())
        assert form["grant_type"] == ["password"]
        assert form["username"] == [EMAIL]
        # Vault password must appear exactly in the grant — nowhere else.
        body = json.dumps(
            {"access_token": "live-access-token", "refresh_token": "live-refresh",
             "token_type": "Bearer", "expires_in": 3600}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/sync":
            self._send_sync()
            return
        self.send_response(404)
        self.end_headers()

    def _send_sync(self) -> None:
        from cloudbrowser.security import vault_crypto as crypto

        auth = self.headers.get("Authorization", "")
        assert auth == "Bearer live-access-token"
        base = self.server  # type: ignore[attr-defined]
        payload = {
            "profile": {
                "key": base.profile_key,  # type: ignore[attr-defined]
                "privateKey": None,
                "organizations": [],
            },
            "ciphers": base.ciphers,  # type: ignore[attr-defined]
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_vault(request):
    from cloudbrowser.security import vault_crypto as crypto

    handler = type("Handler", (FakeVaultHandler,), {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    enc_key, mac_key = crypto.stretched_master_key(PASSWORD, EMAIL, ITERATIONS)
    user_key = hashlib.sha256(b"user-sym-key").digest() + hashlib.sha256(
        b"user-mac-key"
    ).digest()

    def enc_string(plaintext: str, key64: bytes) -> str:
        import base64
        import hmac as hmac_mod

        from cloudbrowser.security import vault_crypto as crypto2

        e, m = crypto2.stretch_to_enc_mac(key64) if hasattr(crypto2, "stretch_to_enc_mac") else (None, None)
        iv = os.urandom(16)
        ct = crypto2.aes_cbc_encrypt(e or key64[:32], iv, plaintext.encode())
        mac = hmac_mod.new(m or key64[32:], iv + ct, hashlib.sha256).digest()
        return "2.{}|{}|{}".format(
            base64.b64encode(iv).decode(),
            base64.b64encode(ct).decode(),
            base64.b64encode(mac).decode(),
        )

    server.enc_key, server.mac_key = enc_key, mac_key  # type: ignore[attr-defined]
    server.profile_key = enc_string(user_key.hex(), enc_key + mac_key)  # type: ignore[attr-defined]
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
def broker_server(monkeypatch, fake_vault):
    monkeypatch.setenv("CB_INSTANCE_ID", "test-broker")
    monkeypatch.setenv("CB_RELEASE_VERSION", "vtest")
    monkeypatch.setenv("CB_PROFILE_ID", "profile-a")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "alice@example.test")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-1")
    monkeypatch.setenv("CB_BINDING_GENERATION", "g1")
    monkeypatch.setenv("CB_BROKER_SHARED_SECRET", "broker-secret-0123456789abcdef")
    monkeypatch.setenv("CB_BROKER_SITE_ID", "site-a")
    monkeypatch.setenv("CB_BROKER_ORIGIN", "https://example.test")
    monkeypatch.setenv("CB_BROKER_USERNAME_SELECTOR", "#username")
    monkeypatch.setenv("CB_BROKER_PASSWORD_SELECTOR", "#password")
    monkeypatch.setenv("CB_BROKER_SUBMIT_SELECTOR", "#submit")
    monkeypatch.setenv("CB_BROKER_SUCCESS_SELECTOR", ".welcome")
    monkeypatch.setenv("CB_VAULT_BASE_URL", f"http://127.0.0.1:{fake_vault.server_address[1]}")
    monkeypatch.setenv("CB_VAULT_EMAIL", EMAIL)
    monkeypatch.setenv("CB_VAULT_PASSWORD", PASSWORD)

    server = create_broker_server(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


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


def test_full_stack_status_only_response(broker_server) -> None:
    port = broker_server.server_address[1]
    status, body = _post_login(
        port,
        {
            "request_id": "req-live-1",
            "auth_token": "broker-secret-0123456789abcdef",
            "username_ref": "PMO Test Site",
            "site_id": "site-a",
            "current_url": "https://example.test/login",
        },
    )
    assert status == 200
    assert body["request_id"] == "req-live-1"
    assert body["status"] == "failed"  # adapter can't run without a real browser
    assert "s3cret-pw" not in json.dumps(body)
    assert "alice@example.test" not in json.dumps(body)


def test_full_stack_rejects_bad_secret(broker_server) -> None:
    port = broker_server.server_address[1]
    status, body = _post_login(
        port,
        {
            "request_id": "req-live-2",
            "auth_token": "wrong-secret",
            "username_ref": "PMO Test Site",
            "site_id": "site-a",
            "current_url": "https://example.test/login",
        },
    )
    assert body["status"] == "failed"
    assert body["error_code"] == "invalid_auth"


def test_full_stack_unknown_ref_fails_closed(broker_server) -> None:
    port = broker_server.server_address[1]
    status, body = _post_login(
        port,
        {
            "request_id": "req-live-3",
            "auth_token": "broker-secret-0123456789abcdef",
            "username_ref": "no-such-item",
            "site_id": "site-a",
            "current_url": "https://example.test/login",
        },
    )
    assert body["status"] == "failed"
    assert body["error_code"] == "internal"  # never leak vault item detail


def test_transport_refuses_foreign_host() -> None:
    transport = make_urllib_transport("http://vault.internal")
    with pytest.raises(ValueError):
        transport("GET", "http://evil.example/api/sync")


def test_health_endpoint(broker_server) -> None:
    port = broker_server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        doc = json.loads(response.read().decode())
    assert doc == {"status": "ok", "component": "credential-broker"}
