"""Live HTTP idempotency prevents repeated credential side effects."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cloudbrowser.credential_broker import (
    AdapterResult,
    BrokerCoordinator,
    GrantAuthorization,
    ServerIdentity,
    SiteDeclaration,
)
from cloudbrowser.credential_broker.api import BrokerHttpServer
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.service import ResolvedBinding
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability

_SECRET = b"idempotency-capability-secret-0123456789"
_NOW = 1_000


def _token(nonce: str) -> str:
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


def _api(
    tmp_path: Path,
    trace: list[str],
    barrier: threading.Barrier | None = None,
) -> BrokerHttpServer:
    binding = ResolvedBinding(
        "profile-a", "principal-a", "browser-a", "site-a", "generation-a"
    )

    def grant(
        live: ResolvedBinding, site_id: str, target_tab_id: str
    ) -> GrantAuthorization:
        return GrantAuthorization(
            username_ref="item-a",
            profile_id=live.profile_id,
            principal_id=live.principal_id,
            browser_id=live.browser_id,
            generation=live.generation,
            site_id=site_id,
            target_tab_id=target_tab_id,
        )

    def fetch(_: str) -> object:
        trace.append("fetch")
        if barrier is not None:
            barrier.wait(timeout=5)
        return object()

    def adapter(_: object, __: object) -> AdapterResult:
        trace.append("fill")
        return AdapterResult("authenticated", True)

    coordinator = BrokerCoordinator(
        resolve_initial=lambda _: binding,
        resolve_pre_fill=lambda _: binding,
        declarations={"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        adapter_selector=lambda *_: adapter,
        grant_resolver=grant,
        target_preflight=lambda *_: ("target-a", "https://login.example.test/"),
    )
    return BrokerHttpServer(
        server_identity=ServerIdentity("credential-broker", "deployment-a"),
        capability_codec=CapabilityCodec(_SECRET),
        capability_audience="credential-broker",
        deployment="deployment-a",
        nonce_store=DurableNonceStore(tmp_path / "nonces.sqlite3"),
        idempotency_store=DurableIdempotencyStore(tmp_path / "idempotency.sqlite3"),
        coordinator=coordinator,
        fetch_credentials=fetch,
        clock=lambda: _NOW + 1,
    )


def _post(api: BrokerHttpServer, token: str) -> dict[str, object]:
    with api.handle("/v1/credential/login", {"capability": token}) as response:
        return dict(response.body)


def test_same_request_with_fresh_nonce_replays_without_second_fetch_or_fill(
    tmp_path: Path,
) -> None:
    trace: list[str] = []
    api = _api(tmp_path, trace)

    first = _post(api, _token("nonce-a"))
    duplicate = _post(api, _token("nonce-b"))

    assert first == duplicate
    assert first["status"] == "authenticated"
    assert trace == ["fetch", "fill"]


def test_duplicate_replays_after_api_restart(tmp_path: Path) -> None:
    trace: list[str] = []
    assert _post(_api(tmp_path, trace), _token("nonce-a"))["status"] == "authenticated"
    assert _post(_api(tmp_path, trace), _token("nonce-b"))["status"] == "authenticated"
    assert trace == ["fetch", "fill"]


def test_concurrent_duplicate_has_one_fetch_and_fill(tmp_path: Path) -> None:
    trace: list[str] = []
    api = _api(tmp_path, trace)
    tokens = [_token(f"nonce-{index}") for index in range(16)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda token: _post(api, token), tokens))

    assert {result["status"] for result in results} == {"authenticated"}
    assert trace == ["fetch", "fill"]
