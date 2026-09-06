"""HttpBrowserTransport must rotate its owner/generation expectations after a successful binding push.

The supervisor adopts a server-minted binding by pushing it to the browser
service, then waking. If the transport keeps expecting the previous owner,
every post-adoption readiness check fails closed even though the browser
rebound correctly.
"""

from __future__ import annotations

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding
from cloudbrowser.browser_slots.http_client import HttpJsonClient
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport


class _FakeHttpClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.current_owner = "principal-old"
        self.current_generation = "generation-old"

    def request(self, method: str, path: str, *, body: str | None = None, headers: dict | None = None):
        self.requests.append((method, path))
        if path == "/browser/binding":
            import json as _json

            payload = _json.loads(body or "{}")
            if (headers or {}).get("X-CB-Trusted-Secret") != "test-shared-secret-0123456789":
                return {"ok": False, "error_code": "binding_not_authorized"}
            self.current_owner = payload["principal_id"]
            self.current_generation = payload["generation"]
            return {"ok": True}
        if path == "/browser/readiness":
            return {
                "owner": self.current_owner,
                "generation": self.current_generation,
                "cdp_ok": True,
                "browser_state": "ready",
            }
        return {"ok": True}


def _binding(owner: str, generation: str) -> BrowserBinding:
    return BrowserBinding(
        profile_id=f"profile-{owner}",
        principal_id=owner,
        browser_id="browser-1",
        generation=generation,
    )


def test_push_binding_rotates_expected_owner_and_generation(monkeypatch):
    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", "test-shared-secret-0123456789")
    http = _FakeHttpClient()
    transport = HttpBrowserTransport(
        http,
        expected_owner="principal-old",
        expected_generation="generation-old",
    )
    new_binding = _binding("principal-new", "generation-new")
    transport.push_binding(new_binding)
    readiness = transport.readiness()
    assert readiness.owner == "principal-new"
    assert readiness.generation == "generation-new"
    assert readiness.cdp_ok is True


def test_push_binding_failure_keeps_previous_expectations(monkeypatch):
    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", "wrong-secret-value-0123456789")
    http = _FakeHttpClient()
    transport = HttpBrowserTransport(
        http,
        expected_owner="principal-old",
        expected_generation="generation-old",
    )
    with pytest.raises(Exception):
        transport.push_binding(_binding("principal-new", "generation-new"))
    readiness = transport.readiness()
    assert readiness.owner == "principal-old"
    assert readiness.generation == "generation-old"
