"""Unit tests for the per-call Vaultwarden producer (broker-only path).

The fake transport replays a realistic Vaultwarden exchange (prelogin,
password grant, sync) with a synthetic account whose ciphers were
encrypted with the same primitives the broker uses to decrypt them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import os
import urllib.parse

import pytest

from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.security import vault_client as vc
from cloudbrowser.security import vault_crypto as crypto

EMAIL = "broker-test@aikumi.pro"
PASSWORD = "correct horse battery staple"
ITERATIONS = 600_000


def enc_string(plaintext: str, key64: bytes) -> str:
    """Type-2 encString builder for the synthetic vault."""
    enc_key, mac_key = crypto.stretch_to_enc_mac(key64)
    iv = os.urandom(16)
    ct = crypto.aes_cbc_encrypt(enc_key, iv, plaintext.encode())
    mac = hmac_mod.new(mac_key, iv + ct, hashlib.sha256).digest()
    return "2.{}|{}|{}".format(
        base64.b64encode(iv).decode(),
        base64.b64encode(ct).decode(),
        base64.b64encode(mac).decode(),
    )


class FakeVault:
    """Builds encrypted payloads and serves them over a fake transport."""

    def __init__(self) -> None:
        self.enc_key, self.mac_key = crypto.stretched_master_key(
            PASSWORD, EMAIL, ITERATIONS
        )
        self.user_key = hashlib.sha256(b"user-sym-key").digest() + hashlib.sha256(
            b"user-mac-key"
        ).digest()
        self.profile_key = enc_string(self.user_key.hex(), self.enc_key + self.mac_key)
        # Profile "key" is itself an encString whose plaintext is the 64-byte
        # user key hex; the client must hex-decode it back to 64 bytes.
        self.ciphers: list[dict] = []
        self.kdf: dict = {"kdf": 0, "kdfIterations": ITERATIONS}
        self.token_ok = True
        self.calls: list[tuple[str, str]] = []

    def add_login(self, *, item_id: str, name: str, username: str, password: str,
                  uri: str = "https://example.test/", totp: str = "") -> None:
        self.ciphers.append(
            {
                "id": item_id,
                "organizationId": None,
                "type": 1,
                "name": enc_string(name, self.user_key),
                "login": {
                    "username": enc_string(username, self.user_key),
                    "password": enc_string(password, self.user_key),
                    "totp": enc_string(totp, self.user_key) if totp else None,
                    "uris": [{"uri": enc_string(uri, self.user_key)}],
                },
            }
        )

    def transport(self, method: str, url: str, *, headers: dict | None = None,
                  body: bytes | None = None) -> tuple[int, bytes]:
        self.calls.append((method, url))
        if url.endswith("/api/accounts/prelogin"):
            return 200, json.dumps(self.kdf).encode()
        if url.endswith("/identity/connect/token"):
            if not self.token_ok:
                return 400, json.dumps({"error": "invalid_grant"}).encode()
            form = urllib.parse.parse_qs((body or b"").decode())
            assert form["grant_type"] == ["password"]
            assert form["username"] == [EMAIL]
            return 200, json.dumps(
                {"access_token": "test-access-token", "refresh_token": "test-refresh",
                 "token_type": "Bearer", "expires_in": 3600}
            ).encode()
        if url.endswith("/api/sync"):
            auth = (headers or {}).get("Authorization", "")
            if auth != "Bearer test-access-token":
                return 401, b"{}"
            return 200, json.dumps(
                {
                    "profile": {
                        "key": self.profile_key,
                        "privateKey": None,
                        "organizations": [],
                    },
                    "ciphers": self.ciphers,
                }
            ).encode()
        return 404, b"{}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fetch_by_name_returns_credential_material() -> None:
    vault = FakeVault()
    vault.add_login(
        item_id="item-1", name="PMO Test Site", username="alice@example.test",
        password="s3cret-pw", uri="https://example.test/",
    )
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password=PASSWORD,
        transport=vault.transport,
    )
    material = client.fetch("PMO Test Site")
    assert isinstance(material, CredentialMaterial)
    assert material.username == "alice@example.test"
    assert material.password == "s3cret-pw"


def test_fetch_by_id_and_by_uri() -> None:
    vault = FakeVault()
    vault.add_login(item_id="abc", name="Named", username="u@x.test", password="p1")
    vault.add_login(item_id="def", name="Other", username="v@x.test", password="p2",
                    uri="https://other.test/login")
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password=PASSWORD,
        transport=vault.transport,
    )
    assert client.fetch("abc").username == "u@x.test"
    assert client.fetch("uri:https://other.test").username == "v@x.test"


def test_fetch_unknown_ref_fails_closed() -> None:
    vault = FakeVault()
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password=PASSWORD,
        transport=vault.transport,
    )
    with pytest.raises(vc.ItemNotFound):
        client.fetch("nope")


def test_ambiguous_name_ref_fails_closed() -> None:
    vault = FakeVault()
    vault.add_login(item_id="a", name="Dup", username="u1@x.test", password="p")
    vault.add_login(item_id="b", name="Dup", username="u2@x.test", password="p")
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password=PASSWORD,
        transport=vault.transport,
    )
    with pytest.raises(vc.AmbiguousItemRef):
        client.fetch("Dup")


def test_wrong_password_fails_with_auth_error() -> None:
    vault = FakeVault()
    vault.add_login(item_id="a", name="Named", username="u@x.test", password="p")
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password="wrong-password",
        transport=vault.transport,
    )
    with pytest.raises((vc.VaultAuthError, crypto.MacVerificationFailed)):
        client.fetch("Named")


def test_argon2_kdf_fails_closed() -> None:
    vault = FakeVault()
    vault.kdf = {"kdf": 1, "kdfIterations": 3, "kdfMemory": 64, "kdfParallelism": 4}
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password=PASSWORD,
        transport=vault.transport,
    )
    with pytest.raises(vc.UnsupportedKdf):
        client.fetch("anything")


def test_no_tokens_retained_on_client() -> None:
    vault = FakeVault()
    vault.add_login(item_id="a", name="Named", username="u@x.test", password="p")
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password=PASSWORD,
        transport=vault.transport,
    )
    client.fetch("Named")
    retained = json.dumps({k: str(v) for k, v in vars(client).items()})
    assert "test-refresh" not in retained
    assert "test-access-token" not in retained


def test_audit_event_has_no_plaintext() -> None:
    event = vc.build_vault_audit_event(
        "vault.fetched",
        username_ref="PMO Test Site",
        item_id="item-1",
        material=CredentialMaterial(username="alice@example.test", password="s3cret-pw"),
    )
    flattened = json.dumps(event)
    assert "s3cret-pw" not in flattened
    assert "alice@example.test" not in flattened
    assert event["username_last4"] == "test"


def test_prelogin_uses_post_and_sync_is_get() -> None:
    vault = FakeVault()
    vault.add_login(item_id="a", name="Named", username="u@x.test", password="p")
    client = vc.VaultwardenClient(
        base_url="https://vault.test", email=EMAIL, password=PASSWORD,
        transport=vault.transport,
    )
    client.fetch("Named")
    methods = {url.split("/api/")[-1]: m for m, url in vault.calls if "/api/" in url}
    assert methods.get("accounts/prelogin") == "POST"
    assert methods.get("sync") == "GET"
