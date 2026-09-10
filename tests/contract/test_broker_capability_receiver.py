"""Security contract for the broker's capability-only receiver."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudbrowser.credential_broker import (
    AdapterResult,
    BrokerCoordinator,
    BrokerHttpServer,
    GrantAuthorization,
    LoginIntent,
    ServerIdentity,
    SiteDeclaration,
)
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.service import ResolvedBinding
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability


_SECRET = b"router-broker-capability-secret-0123456789"
_NOW = 1_000


def _capability(**overrides: object) -> CredentialCapability:
    claims: dict[str, object] = {
        "profile_id": "profile-a",
        "principal_id": "principal-a",
        "browser_id": "browser-a",
        "generation": "generation-a",
        "site_id": "site-a",
        "target_tab_id": "target-a",
        "operation": "credential.login",
        "request_id": "request-a",
        "audience": "credential-broker",
        "deployment": "deployment-a",
        "issued_at": _NOW,
        "expires_at": _NOW + 30,
        "nonce": "nonce-a",
    }
    claims.update(overrides)
    return CredentialCapability(**claims)  # type: ignore[arg-type]


def _binding(**overrides: object) -> ResolvedBinding:
    values: dict[str, object] = {
        "profile_id": "profile-a",
        "principal_id": "principal-a",
        "browser_id": "browser-a",
        "site_id": "site-a",
        "generation": "generation-a",
    }
    values.update(overrides)
    return ResolvedBinding(**values)  # type: ignore[arg-type]


def _grant(binding: ResolvedBinding, site_id: str, target_tab_id: str) -> GrantAuthorization:
    return GrantAuthorization(
        username_ref="server-owned-item",
        profile_id=binding.profile_id,
        principal_id=binding.principal_id,
        browser_id=binding.browser_id,
        generation=binding.generation,
        site_id=site_id,
        target_tab_id=target_tab_id,
    )


def _server(
    path: Path,
    *,
    binding: ResolvedBinding | None = None,
    trace: list[tuple[object, ...]] | None = None,
) -> BrokerHttpServer:
    observed = trace if trace is not None else []
    live = binding or _binding()

    def resolve(_: LoginIntent) -> ResolvedBinding:
        observed.append(("binding",))
        return live

    def preflight(intent: LoginIntent, declaration: object) -> object:
        observed.append(("target", intent.target_tab_id))
        assert getattr(declaration, "site_id") == intent.site_id
        return (intent.target_tab_id, "https://login.example.test/")

    def grant(binding: ResolvedBinding, site_id: str, target_tab_id: str) -> GrantAuthorization:
        observed.append(
            (
                "grant",
                binding.profile_id,
                binding.principal_id,
                binding.browser_id,
                binding.generation,
                site_id,
                target_tab_id,
            )
        )
        return _grant(binding, site_id, target_tab_id)

    def fetch(reference: str) -> object:
        observed.append(("fetch", reference))
        return object()

    def adapter(_: object, material: object) -> AdapterResult:
        observed.append(("adapter", material))
        return AdapterResult("authenticated", True)

    coordinator = BrokerCoordinator(
        resolve_initial=resolve,
        resolve_pre_fill=resolve,
        declarations={"site-a": SiteDeclaration("site-a", "https://login.example.test")},
        adapter_selector=lambda _site, _declaration, _intent: adapter,
        grant_resolver=grant,
        target_preflight=preflight,
    )
    return BrokerHttpServer(
        server_identity=ServerIdentity("credential-broker", "deployment-a"),
        capability_codec=CapabilityCodec(_SECRET),
        capability_audience="credential-broker",
        deployment="deployment-a",
        nonce_store=DurableNonceStore(path),
        idempotency_store=DurableIdempotencyStore(
            path.with_name(f"idempotency-{path.name}")
        ),
        coordinator=coordinator,
        fetch_credentials=fetch,
        clock=lambda: _NOW + 1,
    )


def _post(server: BrokerHttpServer, payload: dict[str, object]) -> dict[str, object]:
    with server.handle("/v1/credential/login", payload) as response:
        return dict(response.body)


def test_receiver_accepts_exact_capability_schema_and_derives_intent_from_claims(
    tmp_path: Path,
) -> None:
    trace: list[tuple[object, ...]] = []
    server = _server(tmp_path / "nonce.sqlite3", trace=trace)
    token = CapabilityCodec(_SECRET).encode(_capability())

    body = _post(server, {"capability": token})

    assert body["request_id"] == "request-a"
    assert body["status"] == "authenticated"
    assert trace.count(("target", "target-a")) == 2
    assert trace.count(("fetch", "server-owned-item")) == 1
    assert trace[-1][0] == "adapter"


def test_receiver_rejects_every_legacy_or_extra_field_without_consuming_nonce(
    tmp_path: Path,
) -> None:
    trace: list[tuple[object, ...]] = []
    server = _server(tmp_path / "nonce.sqlite3", trace=trace)
    token = CapabilityCodec(_SECRET).encode(_capability())

    for extra in (
        {"auth_token": "old-deployment-secret"},
        {"username_ref": "caller-selected-item"},
        {"current_url": "https://login.example.test/"},
        {"idempotency_key": "caller-cache-key"},
        {"site_id": "site-a"},
    ):
        body = _post(server, {"capability": token, **extra})
        assert body["status"] == "failed"
        assert body["error_code"] == "invalid_request"

    assert trace == []
    assert _post(server, {"capability": token})["status"] == "authenticated"


@pytest.mark.parametrize(
    ("claim", "live_value", "expected_code"),
    [
        ("profile_id", "profile-other", "binding_mismatch"),
        ("principal_id", "principal-other", "binding_mismatch"),
        ("browser_id", "browser-other", "binding_mismatch"),
        ("site_id", "site-other", "binding_mismatch"),
        ("generation", "generation-other", "stale_binding"),
    ],
)
def test_every_capability_binding_claim_is_compared_to_live_state(
    tmp_path: Path, claim: str, live_value: str, expected_code: str
) -> None:
    trace: list[tuple[object, ...]] = []
    server = _server(
        tmp_path / f"{claim}.sqlite3",
        binding=_binding(**{claim: live_value}),
        trace=trace,
    )
    token = CapabilityCodec(_SECRET).encode(_capability(nonce=f"nonce-{claim}"))

    body = _post(server, {"capability": token})

    assert body["status"] == "failed"
    assert body["error_code"] == expected_code
    assert not any(phase[0] in {"fetch", "adapter"} for phase in trace)
    assert "principal-a" not in json.dumps(body)


def test_nonce_is_consumed_only_after_signature_context_and_time_validation(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path / "nonce.sqlite3")
    codec = CapabilityCodec(_SECRET)
    valid = codec.encode(_capability())
    tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")

    assert _post(server, {"capability": tampered})["error_code"] == "invalid_capability"
    assert _post(server, {"capability": valid})["status"] == "authenticated"
    replay = _post(server, {"capability": valid})
    assert replay["status"] == "failed"
    assert replay["error_code"] == "capability_replayed"
