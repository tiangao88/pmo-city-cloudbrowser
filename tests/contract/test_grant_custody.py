"""Contracts for offline GrantHub two-leg custody and broker consumption."""

from __future__ import annotations

import base64
import json
import multiprocessing
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded
from cloudbrowser.credential_broker.grant_custody import (
    CustodyCredentialFetcher,
    CustodyGrantStore,
    GrantMaterialError,
    GrantRevoked,
    GrantScope,
    parse_kek,
)
from cloudbrowser.credential_broker.service import ResolvedBinding
from cloudbrowser.security import vault_crypto as crypto

KEK = bytes.fromhex("11" * 32)
VAULT_KEY = bytes.fromhex("22" * 64)
REFRESH_1 = b"refresh-token-one"
REFRESH_2 = b"refresh-token-two"


def scope(**overrides: str) -> GrantScope:
    values = {
        "profile_id": "profile-immutable-1",
        "principal_id": "principal-immutable-1",
        "site_id": "site-1",
        "target_tab_id": "tab-1",
        "browser_id": "browser-1",
        "generation": "generation-1",
    }
    values.update(overrides)
    return GrantScope(**values)


def binding(value: GrantScope | None = None) -> ResolvedBinding:
    value = value or scope()
    return ResolvedBinding(
        profile_id=value.profile_id,
        principal_id=value.principal_id,
        browser_id=value.browser_id,
        site_id=value.site_id,
        generation=value.generation,
    )


def provision(store: CustodyGrantStore, value: GrantScope | None = None) -> None:
    store.provision(
        scope=value or scope(),
        item_ref="vault-item-1",
        vault_key=VAULT_KEY,
        refresh_token=REFRESH_1,
        operator_id="operator-a",
    )


def _vault_transport():
    def enc(value: str) -> str:
        return crypto.encrypt_encstring(value, VAULT_KEY)

    sync = {
        "ciphers": [
            {
                "id": "vault-item-1",
                "type": 1,
                "name": enc("GrantHub fake site"),
                "login": {
                    "username": enc("alice@fake.invalid"),
                    "password": enc("fake-password"),
                    "uris": [{"uri": enc("https://fake.invalid/login")}],
                },
            }
        ]
    }

    def transport(method: str, url: str, *, headers=None, body=None):
        if url.endswith("/identity/connect/token"):
            return 200, json.dumps({"access_token": "access", "expires_in": 300}).encode()
        if url.endswith("/api/sync"):
            return 200, json.dumps(sync).encode()
        raise AssertionError(url)

    return transport


def test_durable_consent_execution_uses_fresh_binding_and_rejects_stale_epoch(tmp_path):
    from dataclasses import replace
    from cloudbrowser.credential_broker.contracts import AuthorizationChanged

    stable = GrantScope.consent(profile_id=scope().profile_id, principal_id=scope().principal_id, site_id=scope().site_id)
    store = CustodyGrantStore(tmp_path / "consent.sqlite3", kek=KEK)
    provision(store, stable)
    fresh = scope(browser_id="slot-2", generation="g-new", target_tab_id="tab-new")
    authorization = store.resolve(binding(fresh), fresh.site_id, fresh.target_tab_id)
    fetcher = CustodyCredentialFetcher(store=store, base_url="https://fake.invalid", transport=_vault_transport())
    seen = []
    assert fetcher.run_authorized(authorization, lambda material: seen.append(material.username) or "submitted") == "submitted"
    assert seen == ["alice@fake.invalid"]
    provision(store, stable)
    with pytest.raises(GrantRevoked):
        fetcher.run_authorized(authorization, lambda material: seen.append("stale"))
    current = store.resolve(binding(fresh), fresh.site_id, fresh.target_tab_id)
    with pytest.raises(AuthorizationChanged):
        fetcher.run_authorized(replace(current, epoch=authorization.epoch), lambda material: seen.append("stale epoch"))
    store.revoke(scope=stable, operator_id="operator")
    with pytest.raises(GrantRevoked):
        fetcher.run_authorized(current, lambda material: seen.append("revoked"))
    assert seen == ["alice@fake.invalid"]


def test_authorized_operation_sqlite_lock_wait_obeys_shared_deadline(tmp_path: Path) -> None:
    path = tmp_path / "grants.sqlite3"
    store = CustodyGrantStore(path, kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    blocker = sqlite3.connect(path, timeout=1.0, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    deadline = BrokerDeadline(started + 0.1)
    fetcher = CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=_vault_transport(),
    )
    try:
        with pytest.raises(BrokerDeadlineExceeded):
            fetcher.run_authorized(
                authorization,
                lambda _material: "not reached",
                deadline=deadline,
            )
        assert time.monotonic() - started < 0.35
    finally:
        blocker.rollback()
        blocker.close()


def test_provision_stores_two_wrapped_legs_and_opaque_authorization(tmp_path: Path) -> None:
    path = tmp_path / "grant-custody.sqlite3"
    store = CustodyGrantStore(path, kek=KEK)
    provision(store)

    authorization = store.resolve(binding(), "site-1", "tab-1")
    assert authorization.username_ref.startswith("grantref:v1.")
    assert authorization.epoch == 1
    assert "principal-immutable-1" not in authorization.username_ref
    assert "vault-item-1" not in authorization.username_ref

    status = store.status(scope(), operator_id="operator-a")
    assert status == {
        "profile_id": "profile-immutable-1",
        "principal_id": "principal-immutable-1",
        "site_id": "site-1",
        "target_tab_id": "tab-1",
        "browser_id": "browser-1",
        "generation": "generation-1",
        "active": True,
        "epoch": 1,
        "has_vault_key": True,
        "has_session_leg": True,
        "usable": True,
    }

    raw = path.read_bytes()
    assert VAULT_KEY not in raw
    assert REFRESH_1 not in raw


def test_reprovisioned_authorization_carries_incremented_epoch(tmp_path: Path) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    first = store.resolve(binding(), "site-1", "tab-1")

    provision(store)
    second = store.resolve(binding(), "site-1", "tab-1")

    assert first.epoch == 1
    assert second.epoch == 2
    assert second.username_ref != first.username_ref


def test_checkout_unwraps_only_inside_one_call_scope(tmp_path: Path) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")

    with store.checkout(authorization.username_ref) as lease:
        assert lease.scope == scope()
        assert lease.item_ref == "vault-item-1"
        assert lease.vault_key == VAULT_KEY
        assert lease.refresh_token == REFRESH_1
        lease.recheck()

    with pytest.raises(GrantMaterialError, match="closed"):
        _ = lease.vault_key


def test_revoke_increments_epoch_and_blocks_new_checkout(tmp_path: Path) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")

    assert store.revoke(scope=scope(), operator_id="operator-a") is True
    status = store.status(scope(), operator_id="operator-a")
    assert status["active"] is False
    assert status["epoch"] == 2
    assert status["has_vault_key"] is False
    assert status["has_session_leg"] is False
    assert status["usable"] is False
    with pytest.raises(LookupError, match="grant revoked"):
        store.resolve(binding(), "site-1", "tab-1")
    with pytest.raises(GrantRevoked):
        with store.checkout(authorization.username_ref):
            pass


def test_authorized_refresh_rotation_uses_gate_connection_without_self_deadlock(
    tmp_path: Path,
) -> None:
    """A rotated session leg must persist inside the held write reservation."""
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    outcomes: list[str] = []
    failures: list[BaseException] = []

    base_transport = _vault_transport()

    def transport(method: str, url: str, *, headers=None, body=None):
        if url.endswith("/identity/connect/token"):
            return 200, json.dumps(
                {
                    "access_token": "access",
                    "expires_in": 300,
                    "refresh_token": REFRESH_2.decode("utf-8"),
                }
            ).encode()
        return base_transport(method, url, headers=headers, body=body)

    fetcher = CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=transport,
    )

    def run() -> None:
        try:
            outcomes.append(
                fetcher.run_authorized(authorization, lambda material: material.username)
            )
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert thread.is_alive() is False, "refresh rotation self-deadlocked under authorization gate"
    assert failures == []
    assert outcomes == ["alice@fake.invalid"]
    with store.checkout(authorization.username_ref) as lease:
        assert lease.refresh_token == REFRESH_2


def test_authorized_refresh_rejection_invalidates_without_self_deadlock(
    tmp_path: Path,
) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    grant = store.resolve(binding(), "site-1", "tab-1")
    authorization = grant

    def rejected_transport(method: str, url: str, *, headers=None, body=None):
        assert url.endswith("/identity/connect/token")
        return 401, b"{}"

    fetcher = CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=rejected_transport,
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            fetcher.run_authorized(authorization, lambda material: "not reached")
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert thread.is_alive() is False, "refresh rejection self-deadlocked under authorization gate"
    assert len(failures) == 1
    assert isinstance(failures[0], GrantRevoked)
    with pytest.raises(LookupError, match="revoked"):
        store.resolve(binding(), "site-1", "tab-1")


def test_refresh_rotation_loses_cleanly_to_concurrent_revocation(tmp_path: Path) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")

    with store.checkout(authorization.username_ref) as lease:
        assert store.revoke(scope=scope(), operator_id="operator-b") is True
        with pytest.raises(GrantRevoked):
            lease.rotate_refresh_token(REFRESH_2)
        with pytest.raises(GrantRevoked):
            lease.recheck()

    with pytest.raises(GrantRevoked):
        with store.checkout(authorization.username_ref):
            pass


def test_revocation_during_session_mint_blocks_sync_and_material_return(tmp_path: Path) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    calls: list[str] = []

    def transport(method: str, url: str, *, headers=None, body=None):
        calls.append(url)
        if url.endswith("/identity/connect/token"):
            assert store.revoke(scope=scope(), operator_id="operator-race") is True
            return 200, json.dumps(
                {"access_token": "must-not-be-used", "expires_in": 300}
            ).encode()
        raise AssertionError("sync must not run after concurrent revocation")

    fetch = CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=transport,
    )

    with pytest.raises(GrantRevoked):
        fetch.fetch(authorization.username_ref)

    assert calls == ["https://fake.invalid/identity/connect/token"]


def test_authorized_operation_blocks_revoke_until_browser_side_effect_finishes(
    tmp_path: Path,
) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    entered = threading.Event()
    release = threading.Event()
    revoked = threading.Event()
    adapter_calls: list[CredentialMaterial] = []
    outcomes: list[str] = []
    failures: list[BaseException] = []

    def operation(material: CredentialMaterial) -> str:
        adapter_calls.append(material)
        entered.set()
        assert release.wait(timeout=2)
        return "submitted"

    def run_operation() -> None:
        try:
            outcomes.append(
                CustodyCredentialFetcher(
                    store=store,
                    base_url="https://fake.invalid",
                    transport=_vault_transport(),
                ).run_authorized(authorization, operation)
            )
        except BaseException as exc:
            failures.append(exc)

    operator_store = CustodyGrantStore(store._path, kek=KEK)

    def revoke() -> None:
        assert entered.wait(timeout=2)
        assert operator_store.revoke(scope=scope(), operator_id="operator-race") is True
        revoked.set()

    operation_thread = threading.Thread(target=run_operation)
    revoke_thread = threading.Thread(target=revoke)
    operation_thread.start()
    revoke_thread.start()
    assert entered.wait(timeout=2)
    assert revoked.wait(timeout=0.1) is False
    release.set()
    operation_thread.join(timeout=2)
    revoke_thread.join(timeout=2)

    assert failures == []
    assert outcomes == ["submitted"]
    assert len(adapter_calls) == 1
    assert revoked.is_set()


def test_cross_process_revoke_waits_for_authorized_browser_side_effect(
    tmp_path: Path,
) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    entered = multiprocessing.Event()
    release = multiprocessing.Event()
    revoked = multiprocessing.Event()

    def operation(material: CredentialMaterial) -> str:
        entered.set()
        assert release.wait(timeout=5)
        return "submitted"

    def run_operation() -> None:
        CustodyCredentialFetcher(
            store=CustodyGrantStore(store._path, kek=KEK),
            base_url="https://fake.invalid",
            transport=_vault_transport(),
        ).run_authorized(authorization, operation)

    def revoke() -> None:
        assert entered.wait(timeout=5)
        operator_store = CustodyGrantStore(store._path, kek=KEK)
        assert operator_store.revoke(scope=scope(), operator_id="operator-process") is True
        revoked.set()

    operation_process = multiprocessing.Process(target=run_operation)
    revoke_process = multiprocessing.Process(target=revoke)
    operation_process.start()
    revoke_process.start()
    assert entered.wait(timeout=5)
    assert revoked.wait(timeout=0.2) is False
    release.set()
    operation_process.join(timeout=5)
    revoke_process.join(timeout=5)

    assert operation_process.exitcode == 0
    assert revoke_process.exitcode == 0
    assert revoked.is_set()


def test_cross_process_reassignment_waits_for_authorized_browser_side_effect(
    tmp_path: Path,
) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    entered = multiprocessing.Event()
    release = multiprocessing.Event()
    reassigned = multiprocessing.Event()

    def operation(material: CredentialMaterial) -> str:
        entered.set()
        assert release.wait(timeout=5)
        return "submitted"

    def run_operation() -> None:
        CustodyCredentialFetcher(
            store=CustodyGrantStore(store._path, kek=KEK),
            base_url="https://fake.invalid",
            transport=_vault_transport(),
        ).run_authorized(authorization, operation)

    def reassign() -> None:
        assert entered.wait(timeout=5)
        operator_store = CustodyGrantStore(store._path, kek=KEK)
        provision(operator_store)
        reassigned.set()

    operation_process = multiprocessing.Process(target=run_operation)
    reassign_process = multiprocessing.Process(target=reassign)
    operation_process.start()
    reassign_process.start()
    assert entered.wait(timeout=5)
    assert reassigned.wait(timeout=0.2) is False
    release.set()
    operation_process.join(timeout=5)
    reassign_process.join(timeout=5)

    assert operation_process.exitcode == 0
    assert reassign_process.exitcode == 0
    assert reassigned.is_set()
    assert store.resolve(binding(), "site-1", "tab-1").epoch == authorization.epoch + 1


def test_run_authorized_uses_callback_material_and_ignores_prefetched_material(
    tmp_path: Path,
) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    seen: list[CredentialMaterial] = []

    result = CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=_vault_transport(),
    ).run_authorized(authorization, lambda material: seen.append(material) or "submitted")

    assert result == "submitted"
    assert [(item.username, item.password) for item in seen] == [
        ("alice@fake.invalid", "fake-password")
    ]


def test_authorized_operation_wipes_lease_after_browser_side_effect(tmp_path: Path) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    captured = []
    original = store.authorized_operation

    @contextmanager
    def capture(grant_ref: str):
        with original(grant_ref) as lease:
            captured.append(lease)
            yield lease

    store.authorized_operation = capture  # type: ignore[method-assign]
    CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=_vault_transport(),
    ).run_authorized(authorization, lambda material: "submitted")

    with pytest.raises(GrantMaterialError, match="closed"):
        _ = captured[0].vault_key


def test_authorized_operation_rejects_stale_epoch_before_browser_side_effect(
    tmp_path: Path,
) -> None:
    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    authorization = store.resolve(binding(), "site-1", "tab-1")
    assert store.revoke(scope=scope(), operator_id="operator-race") is True
    provision(store)
    adapter_calls: list[CredentialMaterial] = []

    with pytest.raises(GrantRevoked):
        CustodyCredentialFetcher(
            store=store,
            base_url="https://fake.invalid",
            transport=_vault_transport(),
        ).run_authorized(authorization, lambda material: adapter_calls.append(material))

    assert adapter_calls == []


def test_fake_vault_mints_from_refresh_leg_rotates_without_static_account(tmp_path: Path) -> None:
    user_key = VAULT_KEY
    calls: list[tuple[str, str, bytes | None]] = []
    expected_refresh = REFRESH_1

    def enc(value: str) -> str:
        return crypto.encrypt_encstring(value, user_key)

    sync = {
        "ciphers": [
            {
                "id": "vault-item-1",
                "type": 1,
                "name": enc("GrantHub fake site"),
                "login": {
                    "username": enc("alice@fake.invalid"),
                    "password": enc("fake-password"),
                    "uris": [{"uri": enc("https://fake.invalid/login")}],
                },
            }
        ]
    }

    def transport(method: str, url: str, *, headers=None, body=None):
        nonlocal expected_refresh
        calls.append((method, url, body))
        if url.endswith("/identity/connect/token"):
            assert body is not None
            form = body.decode()
            assert "username=" not in form
            assert "password=" not in form
            assert "grant_type=refresh_token" in form
            assert base64.urlsafe_b64encode(expected_refresh).decode().rstrip("=") not in form
            # The actual refresh token is URL encoded; ensure the fake server
            # received the expected value without making it part of any result.
            from urllib.parse import parse_qs

            assert parse_qs(form)["refresh_token"] == [expected_refresh.decode()]
            issued_refresh = REFRESH_2 if expected_refresh == REFRESH_1 else None
            expected_refresh = REFRESH_2
            response = {
                "access_token": "fresh-access",
                "expires_in": 300,
            }
            if issued_refresh is not None:
                response["refresh_token"] = issued_refresh.decode()
            return 200, json.dumps(response).encode()
        if url.endswith("/api/sync"):
            assert headers["Authorization"] == "Bearer fresh-access"
            return 200, json.dumps(sync).encode()
        raise AssertionError(url)

    store = CustodyGrantStore(tmp_path / "grant-custody.sqlite3", kek=KEK)
    provision(store)
    fetch = CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=transport,
    )
    auth = store.resolve(binding(), "site-1", "tab-1")

    material = fetch.fetch(auth.username_ref)
    assert isinstance(material, CredentialMaterial)
    assert material.username == "alice@fake.invalid"
    assert material.password == "fake-password"

    # A second read must use the rotated refresh leg, proving that only the
    # wrapped leg was persisted and that no deployment account was used.
    fetch.fetch(auth.username_ref)
    assert len([entry for entry in calls if entry[1].endswith("/api/sync")]) == 2


def test_revocation_stops_new_vault_reads_and_audit_is_status_only(tmp_path: Path) -> None:
    calls: list[str] = []

    def transport(method: str, url: str, *, headers=None, body=None):
        calls.append(url)
        raise AssertionError("transport must not run after revoke")

    store = CustodyGrantStore(tmp_path / "grants.sqlite3", kek=KEK)
    provision(store)
    auth = store.resolve(binding(), "site-1", "tab-1")
    store.revoke(scope=scope(), operator_id="operator-a")
    fetch = CustodyCredentialFetcher(
        store=store,
        base_url="https://fake.invalid",
        transport=transport,
    )

    with pytest.raises(GrantRevoked):
        fetch.fetch(auth.username_ref)
    assert calls == []
    audit = store.audit(operator_id="operator-a")
    serialized = json.dumps(audit, sort_keys=True)
    assert "refresh-token" not in serialized
    assert "22" * 16 not in serialized
    allowed_audit_keys = {
        "event_id",
        "event",
        "operator_id",
        "grant_id",
        "epoch",
        "outcome",
        "created_at",
    }
    assert all(set(event) <= allowed_audit_keys for event in audit)


def test_kek_parser_rejects_ambiguous_or_weak_input() -> None:
    assert parse_kek("hex:" + "ab" * 32) == bytes.fromhex("ab" * 32)
    assert parse_kek("ab" * 32) == bytes.fromhex("ab" * 32)
    with pytest.raises(ValueError):
        parse_kek("too-short")
    with pytest.raises(ValueError):
        parse_kek("raw secret with no explicit encoding")
