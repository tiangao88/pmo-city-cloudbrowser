"""Per-call Vaultwarden producer for the credential broker (broker-only).

Fetches one login cipher's material from a Vaultwarden/Bitwarden-compatible
server. Per Tigo-approved design (spec 95, decision 1): every call performs
a complete unlock — prelogin → password grant → sync → decrypt — and no
token, refresh token, or key is retained after the call returns. Material
exists only inside the broker process and is returned as a
``CredentialMaterial``; audit events carry status plus last-4 references,
never plaintext.

Transport is injected (``transport(method, url, headers=..., body=...)``
returning ``(status, body_bytes)``). The broker runtime wires the real
HTTPS transport; tests use an in-process fake. Only PBKDF2 KDF is
supported (Bitwarden kdf=0); anything else raises ``UnsupportedKdf`` and
fails closed (spec 95: no silent wrong-decrypts).

Resolution by ``username_ref``:
- exact item id (server id) → that item;
- ``uri:<prefix>`` → first cipher whose decrypted URI starts with the
  prefix (ambiguous → ``AmbiguousItemRef``);
- otherwise → case-sensitive decrypted name match (ambiguous →
  ``AmbiguousItemRef``).
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Mapping

from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.security import vault_crypto as crypto

Transport = Callable[..., tuple[int, bytes]]


class VaultClientError(RuntimeError):
    """Base error for the vault producer."""


class VaultAuthError(VaultClientError):
    """Unlock failed: wrong password / rejected grant."""


class ItemNotFound(VaultClientError):
    """No cipher matches the username_ref."""


class AmbiguousItemRef(VaultClientError):
    """Multiple ciphers match the username_ref (refuse to guess)."""


class UnsupportedKdf(VaultClientError):
    """Server reports a KDF other than PBKDF2 (kdf=0)."""


def build_vault_audit_event(
    event_type: str,
    *,
    username_ref: str,
    item_id: str | None,
    material: object | None = None,
) -> dict:
    """Redacted audit event: status fields only, no plaintext material."""
    username_last4 = ""
    if material is not None:
        username = getattr(material, "username", "")
        username_last4 = username[-4:] if username else ""
    return {
        "event": event_type,
        "username_ref": username_ref,
        "item_id": item_id,
        "username_last4": username_last4,
    }


@dataclass(frozen=True)
class _ResolvedCipher:
    item_id: str
    username: str
    password: str
    uris: tuple[str, ...]


class VaultwardenClient:
    """One-call-at-a-time Vaultwarden reader; stateless between calls."""

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        password: str,
        transport: Transport,
        device_identifier: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._transport = transport
        self._device_id = device_identifier or hashlib.sha256(
            ("pmoc-cb-broker:" + email).encode()
        ).hexdigest()[:32]

    # -- public API ----------------------------------------------------------

    def fetch(self, username_ref: str) -> CredentialMaterial:
        """Unlock, sync, resolve ``username_ref``, decrypt, return material."""
        iterations = self._prelogin()
        key64 = self._stretched_keys(iterations)
        sync = self._sync()
        user_key = self._profile_user_key(sync, key64)
        cipher = self._resolve_cipher(sync, username_ref, user_key)
        resolved = self._decrypt_cipher(cipher, user_key)
        return CredentialMaterial(username=resolved.username, password=resolved.password)

    # -- protocol steps --------------------------------------------------------

    def _call(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
              body: bytes | None = None) -> tuple[int, bytes]:
        return self._transport(method, url, headers=dict(headers or {}), body=body)

    def _prelogin(self) -> int:
        status, payload = self._call(
            "POST",
            self._base_url + "/api/accounts/prelogin",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"email": self._email}).encode(),
        )
        if status != 200:
            raise VaultAuthError(f"prelogin failed with status {status}")
        doc = json.loads(payload.decode())
        kind = int(doc.get("kdf", 0) or 0)
        if kind != 0:
            raise UnsupportedKdf(f"unsupported KDF type {kind}; only PBKDF2 is allowed")
        iterations = int(doc.get("kdfIterations", 0) or 0)
        if iterations < 1:
            raise VaultAuthError("prelogin returned no iterations")
        return iterations

    def _stretched_keys(self, iterations: int) -> bytes:
        enc_key, mac_key = crypto.stretched_master_key(
            self._password, self._email, iterations
        )
        return enc_key + mac_key

    def _token(self) -> str:
        body = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "username": self._email,
                "password": self._password,
                "scope": "api offline_access",
                "client_id": "cli",
                "deviceType": "12",
                "deviceIdentifier": self._device_id,
                "deviceName": "pmoc-cb-broker",
            }
        ).encode()
        status, payload = self._call(
            "POST",
            self._base_url + "/identity/connect/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )
        if status != 200:
            raise VaultAuthError(f"password grant failed with status {status}")
        doc = json.loads(payload.decode())
        token = doc.get("access_token")
        if not token:
            raise VaultAuthError("grant returned no access token")
        return str(token)

    def _sync(self) -> dict:
        token = self._token()
        status, payload = self._call(
            "GET",
            self._base_url + "/api/sync",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if status == 401:
            raise VaultAuthError("sync rejected the access token (wrong password?)")
        if status != 200:
            raise VaultClientError(f"sync failed with status {status}")
        doc = json.loads(payload.decode())
        return doc if isinstance(doc, dict) else {}

    # -- key and cipher decryption ---------------------------------------------

    def _profile_user_key(self, sync: dict, key64: bytes) -> bytes:
        profile = sync.get("profile") or {}
        wrapped = profile.get("key")
        if not wrapped:
            raise VaultClientError("sync profile has no wrapped user key")
        try:
            plaintext_hex = crypto.decrypt_encstring(wrapped, key64)
        except crypto.MacVerificationFailed as exc:
            raise VaultAuthError("profile key MAC failed (wrong vault password)") from exc
        except crypto.UnsupportedCipherType as exc:
            raise VaultClientError(f"profile key uses unsupported type: {exc}") from exc
        user_key = bytes.fromhex(plaintext_hex)
        if len(user_key) != 64:
            raise VaultClientError("profile user key must be 64 bytes")
        return user_key

    def _decrypt_cipher(self, cipher: Mapping[str, object], user_key: bytes) -> _ResolvedCipher:
        login = cipher.get("login") or {}
        if not isinstance(login, Mapping):
            login = {}

        def dec(value: object) -> str:
            if not value:
                return ""
            return crypto.decrypt_encstring(str(value), user_key)

        try:
            username = dec(login.get("username"))
            password = dec(login.get("password"))
            uris: list[str] = []
            for entry in login.get("uris") or []:
                uri_value = entry.get("uri") if isinstance(entry, Mapping) else None
                uri = dec(uri_value)
                if uri:
                    uris.append(uri)
            return _ResolvedCipher(
                item_id=str(cipher.get("id") or ""),
                username=username,
                password=password,
                uris=tuple(uris),
            )
        except crypto.MacVerificationFailed as exc:
            raise VaultClientError("cipher MAC failed (org key missing?)") from exc

    def _decrypt_name(self, cipher: Mapping[str, object], user_key: bytes) -> str:
        raw = cipher.get("name")
        if not raw:
            return ""
        try:
            return crypto.decrypt_encstring(str(raw), user_key)
        except crypto.MacVerificationFailed as exc:
            raise VaultClientError("cipher name MAC failed") from exc

    # -- resolution ---------------------------------------------------------------

    def _resolve_cipher(
        self, sync: dict, username_ref: str, user_key: bytes
    ) -> Mapping[str, object]:
        ciphers = [c for c in sync.get("ciphers") or [] if c.get("type") == 1]
        exact_id = [c for c in ciphers if str(c.get("id") or "") == username_ref]
        if len(exact_id) == 1:
            return exact_id[0]
        if username_ref.startswith("uri:"):
            prefix = username_ref[4:]
            matched: list[Mapping[str, object]] = []
            for cipher in ciphers:
                resolved = self._decrypt_cipher(cipher, user_key)
                if any(u.startswith(prefix) for u in resolved.uris):
                    matched.append(cipher)
            if not matched:
                raise ItemNotFound(f"no cipher with URI prefix {prefix!r}")
            if len(matched) > 1:
                raise AmbiguousItemRef(
                    f"{len(matched)} ciphers match URI prefix {prefix!r}"
                )
            return matched[0]
        named = [
            cipher
            for cipher in ciphers
            if self._decrypt_name(cipher, user_key) == username_ref
        ]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            raise AmbiguousItemRef(f"{len(named)} ciphers named {username_ref!r}")
        raise ItemNotFound(f"no cipher matches {username_ref!r}")
