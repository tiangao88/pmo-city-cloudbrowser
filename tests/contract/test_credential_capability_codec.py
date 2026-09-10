"""RED tests for the signed, request-scoped credential capability codec."""

from __future__ import annotations

import pytest

from cloudbrowser.credential_capability import (
    CapabilityCodec,
    CapabilityError,
    CredentialCapability,
)


_SECRET = b"router-broker-capability-secret-0123456789"


def _claims(**overrides: object) -> CredentialCapability:
    values: dict[str, object] = {
        "profile_id": "profile-owner",
        "principal_id": "principal-owner",
        "browser_id": "browser-slot-1",
        "generation": "generation-q-1",
        "site_id": "site-a",
        "target_tab_id": "tab-1",
        "operation": "credential.login",
        "request_id": "request-1",
        "audience": "credential-broker",
        "deployment": "deployment-a",
        "issued_at": 1000,
        "expires_at": 1030,
        "nonce": "nonce-1",
    }
    values.update(overrides)
    return CredentialCapability(**values)  # type: ignore[arg-type]


def test_capability_round_trip_binds_every_required_claim() -> None:
    codec = CapabilityCodec(_SECRET)
    token = codec.encode(_claims())

    decoded = codec.decode(
        token,
        now=1001,
        audience="credential-broker",
        deployment="deployment-a",
        operation="credential.login",
    )

    assert decoded == _claims()
    assert "principal-owner" not in token
    assert "site-a" not in token


def test_capability_signature_and_context_tampering_fail_closed() -> None:
    codec = CapabilityCodec(_SECRET)
    token = codec.encode(_claims())
    parts = token.split(".")
    parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")

    with pytest.raises(CapabilityError):
        codec.decode(".".join(parts), now=1001)
    with pytest.raises(CapabilityError):
        codec.decode(token, now=1001, audience="wrong-audience")
    with pytest.raises(CapabilityError):
        codec.decode(token, now=1001, deployment="wrong-deployment")
    with pytest.raises(CapabilityError):
        codec.decode(token, now=1001, operation="other.operation")


def test_capability_expiry_is_checked_but_replay_is_receiver_owned() -> None:
    codec = CapabilityCodec(_SECRET)
    token = codec.encode(_claims())

    with pytest.raises(CapabilityError):
        codec.decode(token, now=1030)

    # The codec authenticates claims but deliberately has no replay database;
    # the broker receiver consumes nonce-1 exactly once.
    assert codec.decode(token, now=1001).nonce == "nonce-1"
    assert codec.decode(token, now=1001).nonce == "nonce-1"


def test_capability_requires_nonempty_target_and_fixed_time_window() -> None:
    with pytest.raises(ValueError):
        _claims(target_tab_id="")
    with pytest.raises(ValueError):
        _claims(expires_at=1000)
    with pytest.raises(ValueError):
        _claims(expires_at=1401)
    with pytest.raises(ValueError):
        _claims(nonce="nonce/ambiguous")
