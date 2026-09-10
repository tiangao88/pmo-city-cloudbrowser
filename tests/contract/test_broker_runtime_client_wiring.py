"""Default broker browser wiring uses the HTTP client instance directly."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cloudbrowser.credential_broker.adapters.basic import BasicAuthDeclaration
from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.adapters.sso import AuthentikSSODeclaration
from cloudbrowser.credential_broker.contracts import LoginIntent
from cloudbrowser.credential_broker.deadline import BrokerDeadline
from cloudbrowser.credential_broker.runtime import make_default_browser, make_runtime_adapter


class _BrowserHandler(BaseHTTPRequestHandler):
    calls: list[str] = []

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        type(self).calls.append(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        assert payload["target_id"] == "target-a"
        if self.path == "/broker/basic/state":
            self._json(
                {
                    "url": "https://login.example.test/protected",
                    "challenge_origin": "https://login.example.test",
                    "application_authenticated": False,
                }
            )
        elif self.path == "/broker/basic/submit":
            self._json({"ok": True})
        elif self.path == "/broker/authentik/state":
            self._json(
                {
                    "url": "https://app.example.test/home",
                    "modality": None,
                    "identity": "alice",
                }
            )
        elif self.path == "/broker/authentik/proof":
            self._json({"account": "alice"})
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def browser_server():
    handler = type("BrowserHandler", (_BrowserHandler,), {"calls": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", handler.calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _intent() -> LoginIntent:
    return LoginIntent(
        request_id="request-a",
        profile_id="profile-a",
        principal_id="principal-a",
        browser_id="browser-a",
        site_id="site-a",
        target_tab_id="target-a",
        binding_generation="generation-a",
    )


def test_basic_runtime_adapter_reuses_http_client_object(browser_server, monkeypatch) -> None:
    base_url, calls = browser_server
    monkeypatch.setenv("CB_BROWSER_API_URL", base_url)
    adapter = make_runtime_adapter(
        adapter_kind="basic",
        browser=make_default_browser(),
        browser_submit_secret="submit-secret-0123456789",
        intent=_intent(),
    )
    result = adapter(
        BasicAuthDeclaration(
            site_id="site-a",
            origin="https://login.example.test",
            success_path="/protected",
        ),
        CredentialMaterial("alice", "password-a"),
    )
    assert result.status in {"authenticated", "failed"}
    assert "/broker/basic/state" in calls


def test_sso_runtime_adapter_threads_shared_deadline_to_browser_http(
    browser_server, monkeypatch
) -> None:
    base_url, _calls = browser_server
    monkeypatch.setenv("CB_BROWSER_API_URL", base_url)
    deadline = BrokerDeadline(time.monotonic() + 2.0)
    adapter = make_runtime_adapter(
        adapter_kind="sso",
        browser=make_default_browser(),
        browser_submit_secret="submit-secret-0123456789",
        intent=_intent(),
        deadline=deadline,
    )

    assert getattr(adapter, "keywords")["browser"].deadline is deadline


def test_sso_runtime_adapter_reuses_http_client_object(browser_server, monkeypatch) -> None:
    base_url, calls = browser_server
    monkeypatch.setenv("CB_BROWSER_API_URL", base_url)
    adapter = make_runtime_adapter(
        adapter_kind="sso",
        browser=make_default_browser(),
        browser_submit_secret="submit-secret-0123456789",
        intent=_intent(),
    )
    declaration = AuthentikSSODeclaration(
        site_id="site-a",
        entry_url="https://auth.example.test/start",
        idp_origins=("https://auth.example.test",),
        callback_origins=("https://app.example.test",),
        application_origins=("https://app.example.test",),
        application_success_paths=("/home",),
    )
    result = adapter(declaration, CredentialMaterial("alice", "password-a"))
    assert result.status == "authenticated"
    assert "/broker/authentik/state" in calls
