"""RED: HTTP Basic adapter through the deployed broker/browser boundary

The proof is intentionally end strict:

* a disposable local HTTPS Basic-Auth origin issues a real 401 challenge;
* the broker resolves credentials from its vault producer and dispatches the
  declared ``basic`` site to ``BasicAuthAdapter``;
* the browser capability is narrow: current URL, challenge origin,
  submit-basic-auth, and application-authenticated proof only;
* credentials are never embedded in a URL or returned to the caller;
* wrong credentials, challenge loops, and origin changes fail closed.

Production uses the same BasicAuthBrowser protocol over the internal browser
sidecar. The disposable server is local-only and has no external exposure.
"""

from __future__ import annotations

import base64
import json
import ssl
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.runtime import build_broker_api


class _BasicHandler(BaseHTTPRequestHandler):
    expected = "Basic " + base64.b64encode(b"alice:secret-pw").decode("ascii")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != self.expected:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="PMO local test"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"authenticated-basic"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def local_basic_https():
    """Real local HTTPS server with a real Basic challenge."""
    with tempfile.TemporaryDirectory() as temp:
        cert = Path(temp) / "cert.pem"
        key = Path(temp) / "key.pem"
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key), "-out", str(cert), "-days", "1",
                "-nodes", "-subj", "/CN=localhost",
                "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), _BasicHandler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield server, cert
        server.shutdown()
        server.server_close()


@dataclass
class RealBasicBrowser:
    """Narrow test implementation of BasicAuthBrowser over real HTTPS."""

    origin: str
    cafile: str
    challenge: str | None = None
    authenticated: bool = False
    submitted: list[tuple[str, str, str]] | None = None

    def __post_init__(self) -> None:
        self.submitted = []
        self._probe()

    def live_binding(self) -> tuple[str, str]:
        return "pmo-a", "g1"

    def _context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=self.cafile)

    def _probe(self, authorization: str | None = None) -> None:
        headers = {"Authorization": authorization} if authorization else {}
        request = urllib.request.Request(self.origin + "/protected", headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=5, context=self._context()
            ) as response:
                self.authenticated = (
                    response.status == 200
                    and response.read() == b"authenticated-basic"
                )
                self.challenge = None
        except urllib.error.HTTPError as exc:
            self.authenticated = False
            challenge = exc.headers.get("WWW-Authenticate", "")
            self.challenge = (
                self.origin
                if exc.code == 401 and challenge.startswith("Basic ")
                else None
            )

    def current_url(self, *, target_id: str) -> str:
        return self.origin + ("/home" if self.authenticated else "/protected")

    def challenge_origin(self, *, target_id: str) -> str | None:
        return self.challenge

    def has_basic_auth_challenge(self, origin: str, *, target_id: str) -> bool:
        return self.challenge == origin

    def submit_basic_auth(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
    ) -> None:
        assert self.submitted is not None
        self.submitted.append((origin, username, password))
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self._probe("Basic " + token)

    def application_authenticated(self, *, target_id: str) -> bool:
        return self.authenticated


@pytest.fixture()
def basic_env(monkeypatch, local_basic_https):
    server, cert = local_basic_https
    origin = f"https://localhost:{server.server_address[1]}"
    monkeypatch.setenv("CB_INSTANCE_ID", "basic-test")
    monkeypatch.setenv("CB_RELEASE_VERSION", "vtest")
    monkeypatch.setenv("CB_PROFILE_ID", "profile-a")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "pmo-a")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-1")
    monkeypatch.setenv("CB_BINDING_GENERATION", "g1")
    monkeypatch.setenv("CB_BROKER_SHARED_SECRET", "broker-secret-0123456789abcdef")
    monkeypatch.setenv("CB_BROKER_SUBMIT_SECRET", "submit-secret-0123456789abcdef")
    monkeypatch.setenv("CB_BROKER_SITE_ID", "basic-site")
    monkeypatch.setenv("CB_BROKER_ADAPTER", "basic")
    monkeypatch.setenv("CB_BROKER_ORIGIN", origin)
    monkeypatch.setenv("CB_BROKER_SUCCESS_PATH", "/home")
    monkeypatch.setenv("CB_VAULT_BASE_URL", "https://vault.example.invalid")
    monkeypatch.setenv("CB_VAULT_EMAIL", "broker@example.test")
    monkeypatch.setenv("CB_VAULT_PASSWORD", "not-used-by-injected-fetcher")
    return origin, str(cert)


def _run(api, *, username_ref: str = "basic-vault-item") -> dict:
    with api.handle(
        "/v1/credential/login",
        {
            "request_id": "req-basic-1",
            "auth_token": "broker-secret-0123456789abcdef",
            "usernamefinder_ref": username_ref,
            "username_ref": username_ref,
            "site_id": "basic-site",
            "current_url": "https://caller.example.invalid/ignored",
            "target_tab_id": "target-basic-1",
        },
    ) as response:
        return dict(response.body)


def test_basic_adapter_real_local_https_challenge_authenticated(basic_env) -> None:
    origin, cert = basic_env
    browser = RealBasicBrowser(origin, cert)
    api = build_broker_api(
        browser_factory=lambda: browser,
        credential_fetcher=lambda ref: CredentialMaterial("alice", "secret-pw"),
    )

    body = _run(api)

    assert body == {
        "request_id": "req-basic-1",
        "status": "authenticated",
        "error_code": None,
        "duration_ms": 0,
    }
    assert browser.submitted == [(origin, "alice", "secret-pw")]
    serialized = json.dumps(body)
    assert "secret-pw" not in serialized
    assert "alice" not in serialized
    assert "@" not in serialized


def test_basic_adapter_wrong_vault_password_fails_closed(basic_env) -> None:
    origin, cert = basic_env
    browser = RealBasicBrowser(origin, cert)
    api = build_broker_api(
        browser_factory=lambda: browser,
        credential_fetcher=lambda ref: CredentialMaterial("alice", "wrong-pw"),
    )

    body = _run(api)

    assert body["status"] == "failed"
    assert body["error_code"] == "challenge_loop"
    assert "wrong-pw" not in json.dumps(body)


def test_basic_adapter_rejects_live_binding_mismatch_before_credentials(
    basic_env, monkeypatch
) -> None:
    origin, cert = basic_env
    browser = RealBasicBrowser(origin, cert)
    browser.live_binding = lambda: ("pmo-other", "g1")  # type: ignore[method-assign]
    fetched = False

    def fetch(_ref: str) -> CredentialMaterial:
        nonlocal fetched
        fetched = True
        return CredentialMaterial("alice", "secret-pw")

    api = build_broker_api(browser_factory=lambda: browser, credential_fetcher=fetch)
    body = _run(api)

    assert body["status"] == "failed"
    assert body["error_code"] == "internal"
    assert fetched is True
    assert browser.submitted == []


def test_basic_adapter_declared_origin_is_exact(basic_env, monkeypatch) -> None:
    origin, cert = basic_env
    browser = RealBasicBrowser(origin, cert)
    monkeypatch.setenv("CB_BROKER_ORIGIN", "https://localhost:1")
    api = build_broker_api(
        browser_factory=lambda: browser,
        credential_fetcher=lambda ref: CredentialMaterial("alice", "secret-pw"),
    )

    body = _run(api)

    assert body["status"] == "failed"
    assert body["error_code"] == "adapter_invalid_target"
    assert browser.submitted == []
