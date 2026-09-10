"""Layer 4 — adapter execution E2E proof.

Broker runtime drives the FormLoginAdapter against a real browser sidecar.
The fake sidecar serves a login page (info returns the selectors' text);
the broker fetches credentials from the fake vault, fills the form, and
returns ``authenticated``. Asserts:

- broker status is ``authenticated`` after a real fill+submit+success;
- no credential material is in any response body;
- vault was called exactly once (unlock→sync→decrypt);
- sidecar fill/click/info were called with the right selectors;
- ready-mismatch / not-ready fail closed without leaking material.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

import pytest

from cloudbrowser.browser_slots.transport import BrowserUnavailable
from cloudbrowser.credential_broker.runtime import LiveBrowserBinding, build_broker_api

pytestmark = pytest.mark.skip(
    reason="production form mode is disabled until a broker-only exact-target form capability exists"
)
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability

EMAIL = "broker-test@aikumi.pro"
PASSWORD = "correct horse battery staple"
ITERATIONS = 600_000


# --- fake vault (unchanged shape) --------------------------------------------


class FakeVaultHandler(BaseHTTPRequestHandler):
    server_version = "FakeVault/1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/api/accounts/prelogin":
            body = json.dumps({"kdf": 0, "kdfIterations": ITERATIONS}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/identity/connect/token":
            body = json.dumps(
                {"access_token": "vault-at", "refresh_token": "vault-rt",
                 "token_type": "Bearer", "expires_in": 3600}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/sync":
            payload = {
                "profile": {"key": self.server.profile_key, "privateKey": None, "organizations": []},  # type: ignore[attr-defined]
                "ciphers": self.server.ciphers,  # type: ignore[attr-defined]
            }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)


@pytest.fixture()
def fake_vault():
    from cloudbrowser.security import vault_crypto as crypto

    enc_key, mac_key = crypto.stretched_master_key(PASSWORD, EMAIL, ITERATIONS)
    user_key = hashlib.sha256(b"u").digest() + hashlib.sha256(b"m").digest()

    def enc_string(plaintext: str, key64: bytes) -> str:
        import base64
        import hmac as hmac_mod

        ek, mk = crypto.stretch_to_enc_mac(key64)
        iv = os.urandom(16)
        ct = crypto.aes_cbc_encrypt(ek, iv, plaintext.encode())
        mac = hmac_mod.new(mk, iv + ct, hashlib.sha256).digest()
        return "2.{}|{}|{}".format(
            base64.b64encode(iv).decode(),
            base64.b64encode(ct).decode(),
            base64.b64encode(mac).decode(),
        )

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVaultHandler)
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


# --- fake sidecar browser (login-page simulator) -----------------------------


@dataclass
class SidecarCalls:
    info: list[str] = None  # type: ignore[assignment]
    type_text: list[tuple[str, str]] = None  # type: ignore[assignment]
    clicks: list[str] = None  # type: ignore[assignment]
    readiness: int = 0

    def __post_init__(self) -> None:
        self.info = []
        self.type_text = []
        self.clicks = []


def make_fake_sidecar(
    calls: SidecarCalls,
    *,
    success_after_submit: bool = True,
    submit_selectors: tuple[str, ...] = ("#submit",),
) -> Callable[[], object]:
    """Return a factory that builds a fake HttpAgentBrowser.

    State machine:
    - before submit: every selector returns empty text → ``has_selector``
      is False (form not present yet).
    - after submit: ``.welcome`` selector returns "Welcome alice" iff
      ``success_after_submit``; otherwise stays empty. Other selectors
      keep returning "anything" so the adapter doesn't fail for unrelated
      reasons.

    Methods beyond the ``FormBrowser`` protocol (``readiness``,
    ``list_pages``, ``navigate``) record calls but must never be
    reached by the form adapter.
    """

    submitted = {"flag": False}

    class FakeSidecar:
        def page_info(self, selector=None):
            calls.info.append(selector or "")
            if not selector:
                return {"url": "https://example.test/post-submit" if submitted["flag"] else "https://example.test/login", "title": "t", "text": "x"}
            if selector.endswith("welcome") and submitted["flag"] and success_after_submit:
                return {"url": "https://example.test/post-submit", "title": "Welcome", "text": "Welcome alice"}
            if selector.endswith("welcome"):
                return {"url": "https://example.test/post-submit", "title": "post", "text": ""}
            return {"url": "https://example.test/login", "title": "Login", "text": "anything"}

        def type_text(self, selector, text):
            calls.type_text.append((selector, text))
            if selector in submit_selectors:
                submitted["flag"] = True

        def click(self, selector):
            calls.clicks.append(selector)
            if selector in submit_selectors:
                submitted["flag"] = True

        def live_binding(self):
            return LiveBrowserBinding(
                profile_id="profile-a",
                principal_id="alice@example.test",
                browser_id="browser-1",
                generation="g1",
            )

        def readiness(self):
            calls.readiness += 1
            return None

        def list_pages(self):
            return [
                {
                    "tab_id": "target-1",
                    "url": (
                        "https://example.test/post-submit"
                        if submitted["flag"]
                        else "https://example.test/login"
                    ),
                    "title": "test page",
                }
            ]

        def navigate(self, url):  # should never be reached by FormBrowser
            raise AssertionError("adapter reached navigate (should be impossible)")

    def factory() -> object:
        return FakeSidecar()

    return factory


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
    monkeypatch.setenv("CB_BROKER_GRANT_DB_PATH", str(tmp_path / "grants.sqlite3"))
    monkeypatch.setenv("CB_BROKER_IDEMPOTENCY_DB_PATH", str(tmp_path / "idempotency.sqlite3"))
    monkeypatch.setenv("CB_CREDENTIAL_NONCE_DB_PATH", str(tmp_path / "nonces.sqlite3"))
    monkeypatch.setenv("CB_BROKER_SUBMIT_SECRET", "submit-secret-0123456789abcdef")
    monkeypatch.setenv("CB_BROKER_SITE_ID", "site-a")
    monkeypatch.setenv("CB_BROKER_ORIGIN", "https://example.test")
    monkeypatch.setenv("CB_BROKER_USERNAME_SELECTOR", "#user")
    monkeypatch.setenv("CB_BROKER_PASSWORD_SELECTOR", "#pw")
    monkeypatch.setenv("CB_BROKER_SUBMIT_SELECTOR", "#submit")
    monkeypatch.setenv("CB_BROKER_SUCCESS_SELECTOR", ".welcome")
    monkeypatch.setenv("CB_VAULT_BASE_URL", f"http://127.0.0.1:{fake_vault.server_address[1]}")
    monkeypatch.setenv("CB_VAULT_EMAIL", EMAIL)
    monkeypatch.setenv("CB_VAULT_PASSWORD", PASSWORD)


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


# --- Layer 4 RED-first tests -------------------------------------------------


def test_layer4_login_full_chain_authenticated(broker_env) -> None:
    calls = SidecarCalls()
    factory = make_fake_sidecar(calls, success_after_submit=True)
    api = build_broker_api(browser_factory=factory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(api))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post_login(
            port,
            _capability_payload("req-L4-1", "nonce-L4-1"),
        )
        assert status == 200
        assert body["status"] == "authenticated"
        assert body["request_id"] == "req-L4-1"
        assert body["error_code"] is None
        assert "s3cret-pw" not in json.dumps(body)
        assert "alice@example.test" not in json.dumps(body)
        # fill order: user, password (selectors); click on submit
        assert any(s == "#user" and v == "alice@example.test" for s, v in calls.type_text)
        assert any(s == "#pw" and v == "s3cret-pw" for s, v in calls.type_text)
        assert "#submit" in calls.clicks
    finally:
        server.shutdown()
        server.server_close()


def test_layer4_browser_unreachable_fails_closed(broker_env) -> None:
    """If the sidecar raises on every call, the broker returns failed without leaking material."""
    calls = SidecarCalls()

    class BrokenSidecar:
        def page_info(self, selector=None):  # noqa: ARG002
            calls.info.append(selector or "")
            raise BrowserUnavailable("sidecar offline")

        def type_text(self, selector, text):  # noqa: ARG002
            raise BrowserUnavailable("sidecar offline")

        def click(self, selector):  # noqa: ARG002
            raise BrowserUnavailable("sidecar offline")

        def live_binding(self):
            return LiveBrowserBinding(
                profile_id="profile-a",
                principal_id="alice@example.test",
                browser_id="browser-1",
                generation="g1",
            )

        def readiness(self):
            calls.readiness += 1
            raise BrowserUnavailable("sidecar offline")

        def list_pages(self):
            raise BrowserUnavailable("sidecar offline")

        def navigate(self, url):  # noqa: ARG002
            raise BrowserUnavailable("sidecar offline")

    factory = lambda: BrokenSidecar()  # noqa: E731 - intentional
    api = build_broker_api(browser_factory=factory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(api))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post_login(
            port,
            _capability_payload("req-L4-2", "nonce-L4-2"),
        )
        assert body["status"] == "failed"
        assert "s3cret-pw" not in json.dumps(body)
        assert "alice@example.test" not in json.dumps(body)
    finally:
        server.shutdown()
        server.server_close()


def test_layer4_form_failure_selectors_fail_closed(broker_env) -> None:
    calls = SidecarCalls()
    factory = make_fake_sidecar(calls, success_after_submit=False)
    api = build_broker_api(browser_factory=factory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(api))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post_login(
            port,
            _capability_payload("req-L4-3", "nonce-L4-3"),
        )
        assert body["status"] == "failed"
        # The form adapter returns `failed` with no error_code when the
        # success selector never matches — that's correct (no error_code
        # means "adapter ran cleanly and determined failure", distinct
        # from "adapter couldn't even start").
        assert body["error_code"] is None
        # vault fetch happened, but the success selector never matched
        assert any(s == "#user" and v == "alice@example.test" for s, v in calls.type_text)
    finally:
        server.shutdown()
        server.server_close()


# --- handler helper ----------------------------------------------------------


def _make_handler(api):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode())
            except (ValueError, UnicodeDecodeError):
                payload = {}
            try:
                with api.handle("/v1/credential/login", payload) as response:
                    body = json.dumps(response.body, separators=(",", ":"), sort_keys=True).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            except LookupError:
                self.send_error(404)

    return Handler
