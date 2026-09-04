"""Security and durability tests for the PMO-owned identity-link service."""

from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import threading

from cloudbrowser.edge_auth import parse_edge_identity
from cloudbrowser.identity_link_service import IdentityLinkStore, create_identity_link_server
from cloudbrowser.identity_links import IdentityLinkClient, IdentityLinkKey

_SECRET = "identity-link-test-secret-012345"
_ISSUER = "https://auth.example.test"
_REALM = "tinyauth.example.test"


def _identity(*, sub: str | None = "oidc-sub-1", user: str = "local-owner", email: str = "owner@example.com"):
    headers = {
        "Remote-User": user,
        "Remote-Email": email,
        "Remote-Groups": "PMOC_Users",
    }
    if sub is not None:
        headers["Remote-Sub"] = sub
    identity = parse_edge_identity(headers)
    assert identity is not None
    return identity


def _serve(tmp_path: Path):
    store = IdentityLinkStore(tmp_path / "identity-links.sqlite3", clock=lambda: 100.0)
    server = create_identity_link_server(
        store,
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = IdentityLinkClient(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
    )
    return store, server, thread, client


def _close(server, thread) -> None:
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def test_oidc_link_is_server_owned_stable_and_email_is_not_sent(tmp_path: Path) -> None:
    store, server, thread, client = _serve(tmp_path)
    try:
        identity = _identity(sub="oidc-sub-1", email="first@example.com")
        principal = client.resolve(identity)
        assert principal is not None
        assert principal.startswith("pmo-")

        second = _identity(sub="oidc-sub-1", email="changed@example.com")
        assert client.resolve(second) == principal

        with sqlite3.connect(tmp_path / "identity-links.sqlite3") as db:
            row = db.execute(
                "SELECT namespace, issuer_or_realm, external_id, pmo_user_id FROM identity_links"
            ).fetchone()
        assert row == ("oidc", _ISSUER, "oidc-sub-1", principal)
        assert "first@example.com" not in json.dumps(row)
        assert "changed@example.com" not in json.dumps(row)
    finally:
        _close(server, thread)


def test_local_tinyauth_user_is_the_fallback_key_not_email(tmp_path: Path) -> None:
    store, server, thread, client = _serve(tmp_path)
    try:
        identity = _identity(sub=None, user="local-owner", email="pseudo@example.com")
        principal = client.resolve(identity)
        assert principal is not None
        assert client.resolve(_identity(sub=None, user="local-owner", email="other@example.com")) == principal
        with sqlite3.connect(tmp_path / "identity-links.sqlite3") as db:
            row = db.execute(
                "SELECT namespace, issuer_or_realm, external_id FROM identity_links"
            ).fetchone()
        assert row == ("tinyauth-local", _REALM, "local-owner")
    finally:
        _close(server, thread)


def test_email_without_authoritative_subject_or_user_cannot_resolve(tmp_path: Path) -> None:
    _store, server, thread, client = _serve(tmp_path)
    try:
        identity = parse_edge_identity(
            {"Remote-Email": "owner@example.com", "Remote-Groups": "PMOC_Users"}
        )
        assert identity is not None
        assert client.resolve(identity) is None
    finally:
        _close(server, thread)


def test_group_gate_and_unknown_authority_fail_closed(tmp_path: Path) -> None:
    _store, server, thread, client = _serve(tmp_path)
    try:
        no_group = parse_edge_identity(
            {"Remote-Sub": "oidc-sub-1", "Remote-Groups": "Other"}
        )
        assert no_group is not None
        assert client.resolve(no_group) is None

        unknown = _identity(sub="oidc-sub-1")
        assert client.resolve(unknown) is not None
        bad_issuer = IdentityLinkKey("oidc", "https://attacker.example", "oidc-sub-2")
        assert client.resolve_key(bad_issuer, groups=("PMOC_Users",)) is None
    finally:
        _close(server, thread)


def test_revocation_is_a_tombstone_and_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "identity-links.sqlite3"
    store = IdentityLinkStore(db_path, clock=lambda: 100.0)
    key = IdentityLinkKey("oidc", _ISSUER, "oidc-sub-1")
    principal = store.resolve(key, groups=("PMOC_Users",))
    assert principal is not None
    assert store.revoke(key) is True
    assert store.resolve(key, groups=("PMOC_Users",)) is None

    restarted = IdentityLinkStore(db_path, clock=lambda: 200.0)
    assert restarted.resolve(key, groups=("PMOC_Users",)) is None
    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT pmo_user_id, revoked_at FROM identity_links WHERE external_id = ?",
            ("oidc-sub-1",),
        ).fetchone()
    assert row[0] == principal
    assert row[1] == 100.0


def test_concurrent_first_login_converges_to_one_principal(tmp_path: Path) -> None:
    db_path = tmp_path / "identity-links.sqlite3"
    stores = [IdentityLinkStore(db_path) for _ in range(4)]
    key = IdentityLinkKey("oidc", _ISSUER, "oidc-sub-race")
    results: list[str | None] = []
    lock = threading.Lock()

    def resolve(store: IdentityLinkStore) -> None:
        value = store.resolve(key, groups=("PMOC_Users",))
        with lock:
            results.append(value)

    threads = [threading.Thread(target=resolve, args=(store,)) for store in stores]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert len(results) == 4
    assert len(set(results)) == 1
    assert results[0] is not None


def test_service_rejects_caller_supplied_pmo_id(tmp_path: Path) -> None:
    _store, server, thread, _client = _serve(tmp_path)
    try:
        connection = HTTPConnection(*server.server_address, timeout=3)
        body = json.dumps(
            {
                "namespace": "oidc",
                "issuer_or_realm": _ISSUER,
                "external_id": "oidc-sub-1",
                "groups": ["PMOC_Users"],
                "pmo_user_id": "pmo-attacker-controlled",
            }
        ).encode()
        connection.request(
            "POST",
            "/v1/resolve",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "X-CB-Identity-Link-Secret": _SECRET,
            },
        )
        response = connection.getresponse()
        response_body = response.read()
        connection.close()
        assert response.status == 400
        assert b"pmo-attacker-controlled" not in response_body
    finally:
        _close(server, thread)
