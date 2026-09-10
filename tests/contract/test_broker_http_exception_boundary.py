"""HTTP broker boundary must contain arbitrary dependency failures."""

from __future__ import annotations

import json
import threading
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from cloudbrowser.credential_broker import (
    AdapterResult,
    BrokerCoordinator,
    GrantAuthorization,
    LoginIntent,
    ServerIdentity,
    SiteDeclaration,
)
from cloudbrowser.credential_broker.api import BrokerHttpServer
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.runtime import create_broker_http_server
from cloudbrowser.credential_broker.service import ResolvedBinding
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability

_SECRET = b"boundary-capability-secret-0123456789"
_NOW = 1_000


def _capability(nonce: str) -> str:
    return CapabilityCodec(_SECRET).encode(
        CredentialCapability(
            profile_id="profile-a",
            principal_id="principal-a",
            browser_id="browser-a",
            generation="generation-a",
            site_id="site-a",
            target_tab_id="target-a",
            operation="credential.login",
            request_id="request-a",
            audience="credential-broker",
            deployment="deployment-a",
            issued_at=_NOW,
            expires_at=_NOW + 30,
            nonce=nonce,
        )
    )


def _grant(binding: ResolvedBinding, site_id: str, target_tab_id: str) -> GrantAuthorization:
    return GrantAuthorization(
        username_ref="server-item",
        profile_id=binding.profile_id,
        principal_id=binding.principal_id,
        browser_id=binding.browser_id,
        generation=binding.generation,
        site_id=site_id,
        target_tab_id=target_tab_id,
    )


@contextmanager
def _server(tmp_path: Path, phase: str):
    binding = ResolvedBinding(
        "profile-a", "principal-a", "browser-a", "site-a", "generation-a"
    )

    def resolve(_: LoginIntent) -> ResolvedBinding:
        if phase == "binding":
            raise RuntimeError("binding-secret-detail")
        return binding

    def preflight(*_: object) -> object:
        if phase == "preflight":
            raise RuntimeError("preflight-secret-detail")
        return ("target-a", "https://login.example.test/")

    def fetch(_: str) -> object:
        if phase == "fetch":
            raise RuntimeError("fetch-secret-detail")
        return object()

    def adapter(_: object, __: object) -> AdapterResult:
        if phase == "adapter":
            raise RuntimeError("adapter-secret-detail")
        return AdapterResult("authenticated", True)

    coordinator = BrokerCoordinator(
        resolve_initial=resolve,
        resolve_pre_fill=resolve,
        declarations={"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        adapter_selector=lambda *_: adapter,
        grant_resolver=_grant,
        target_preflight=preflight,
    )
    api = BrokerHttpServer(
        server_identity=ServerIdentity("credential-broker", "deployment-a"),
        capability_codec=CapabilityCodec(_SECRET),
        capability_audience="credential-broker",
        deployment="deployment-a",
        nonce_store=DurableNonceStore(tmp_path / f"{phase}-nonce.sqlite3"),
        idempotency_store=DurableIdempotencyStore(tmp_path / f"{phase}-idempotency.sqlite3"),
        coordinator=coordinator,
        fetch_credentials=fetch,
        clock=lambda: _NOW + 1,
    )
    server = create_broker_http_server(api, ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("phase", ["binding", "preflight", "fetch", "adapter"])
def test_http_boundary_returns_status_only_for_arbitrary_exception(
    tmp_path: Path, phase: str
) -> None:
    with _server(tmp_path, phase) as port:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/credential/login",
            data=json.dumps({"capability": _capability(f"nonce-{phase}")}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read())

    assert response.status == 200
    assert body == {
        "request_id": "request-a",
        "status": "failed",
        "error_code": "internal_error",
        "duration_ms": 0,
    }
    assert "secret-detail" not in json.dumps(body)

    replay_api = BrokerHttpServer(
        server_identity=ServerIdentity("credential-broker", "deployment-a"),
        capability_codec=CapabilityCodec(_SECRET),
        capability_audience="credential-broker",
        deployment="deployment-a",
        nonce_store=DurableNonceStore(tmp_path / f"{phase}-nonce.sqlite3"),
        idempotency_store=DurableIdempotencyStore(
            tmp_path / f"{phase}-idempotency.sqlite3"
        ),
        coordinator=BrokerCoordinator(
            resolve_initial=lambda _: ResolvedBinding(
                "profile-a", "principal-a", "browser-a", "site-a", "generation-a"
            ),
            resolve_pre_fill=lambda _: ResolvedBinding(
                "profile-a", "principal-a", "browser-a", "site-a", "generation-a"
            ),
            declarations={
                "site-a": SiteDeclaration("site-a", "https://login.example.test")
            },
            adapter_selector=lambda *_: lambda _d, _m: AdapterResult(
                "authenticated", True
            ),
            grant_resolver=_grant,
            target_preflight=lambda *_: ("target-a", "https://login.example.test/"),
        ),
        fetch_credentials=lambda _: object(),
        clock=lambda: _NOW + 1,
    )
    with replay_api.handle(
        "/v1/credential/login", {"capability": _capability(f"replay-{phase}")}
    ) as replay:
        assert replay.body == {
            "request_id": "request-a",
            "status": "failed",
            "error_code": "unknown_outcome",
            "duration_ms": 0,
        }
