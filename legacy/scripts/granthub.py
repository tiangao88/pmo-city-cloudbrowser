#!/usr/bin/env python3
"""GrantHub shared library — router (grant store/status) + slot broker (unwrap).

Pure-python AES-256-GCM (gcm.py on vendored pyaes) — zero C deps, runs in
the slim router container and the neko slot containers alike.

Per-user grant store (spec 34 §3 Phase 2 — "no honeypot", everything for
user U lives in U's folder):

    <GRANT_ROOT>/<email>/grant/grant.json  — metadata + wrapped key
    <GRANT_ROOT>/<email>/grant/k_user.bin  — 32-byte AES-256 wrapping key

grant.json (0600):
    { "user": <email>, "wrapped_key": {"nonce": b64, "ct": b64, "tag": b64},
      "scope": "PMO City vault", "issued_at": iso, "revoked": false }

Invariants:
- master password is NEVER stored
- revocation: mark revoked AND delete k_user.bin → unwrap fails hard
- unwrap() refuses revoked/missing grants; AES-GCM tag guards tampering
"""
import base64
import json
import os
import re as _re
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import gcm  # noqa: E402

SCOPE_DEFAULT = "PMO City vault"
KEY_LEN = 32  # AES-256


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _b64d(s: str) -> bytes:
    return base64.b64decode(s)


_EMAIL_RE = _re.compile(
    r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")


def canonical_email(identity) -> str | None:
    """Strict canonical email grammar (audit B5 — path traversal from
    unvalidated identities). Accepts ONLY lowercase, dot-separated labels
    with a dot-joined multi-label domain and a >=2-char TLD; rejects every
    separator, whitespace, control char, mixed case, consecutive dots and
    any path-like input ('/', '\\', '..', '%xx', ':'...). Returns the
    canonical lowercase form or None. Callers MUST use the returned value
    (never the raw input) for any filesystem path."""
    if not isinstance(identity, str):
        return None
    v = identity.strip().lower()
    if len(v) > 254 or not v:
        return None
    if ".." in v or v.startswith(".") or v.endswith("."):
        return None
    if not _EMAIL_RE.match(v):
        return None
    local, _, domain = v.partition("@")
    if not local or not domain:
        return None
    tld = domain.rsplit(".", 1)[-1]
    if len(tld) < 2:
        return None
    return v


def grant_dir(root: str, email: str) -> str:
    """Identity-derived grant folder. Validates the identity against the
    canonical email grammar FIRST (audit B5), then verifies the resolved
    path stays inside `root` — a hostile or noncanonical identity raises
    GrantError before any filesystem access."""
    canon = canonical_email(email)
    if canon is None:
        raise GrantError(f"non-canonical identity: {email!r}")
    p = os.path.join(root, canon, "grant")
    real_root = os.path.realpath(root)
    real_p = os.path.realpath(p)
    if not real_p.startswith(real_root + os.sep):
        raise GrantError(f"identity escapes grant root: {email!r}")
    return p


def grant_path(root: str, email: str) -> str:
    return os.path.join(grant_dir(root, email), "grant.json")


def kuser_path(root: str, email: str) -> str:
    return os.path.join(grant_dir(root, email), "k_user.bin")


def _atomic_write(path: str, data: bytes, mode: int = 0o600):
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fchmod(f.fileno(), mode)
    os.replace(tmp, path)


def wrap(user_key_b64: str, k_user: bytes | None = None):
    """Wrap a user key (b64 string from the vault's in-memory key) with a
    fresh or supplied AES-256 key. Returns (payload_dict, k_user_bytes)."""
    return wrap_bytes(_b64d(user_key_b64), k_user)


def wrap_bytes(raw: bytes, k_user: bytes | None = None):
    """AES-256-GCM wrap of arbitrary bytes (user key b64 or a vault
    refresh token) with a fresh or supplied K_user. Returns the
    {nonce, ct, tag} payload dict (never the plaintext)."""
    if k_user is None:
        k_user = secrets.token_bytes(KEY_LEN)
    iv = secrets.token_bytes(12)
    ct, tag = gcm.gcm_encrypt(k_user, iv, raw)
    payload = {
        "nonce": _b64e(iv),
        "ct": _b64e(ct),
        "tag": _b64e(tag),
    }
    return payload, k_user


def save_grant(root: str, email: str, wrapped: dict, scope: str = SCOPE_DEFAULT,
               k_user: bytes | None = None,
               wrapped_session: dict | None = None) -> dict:
    """Persist the grant for email. k_user defaults to a fresh random key.
    wrapped_session (spec 59): optional AES-GCM-wrapped vault refresh
    token — the session-token leg that makes the grant USABLE by the
    broker without any user unlock. Returns the stored record."""
    if k_user is None:
        k_user = secrets.token_bytes(KEY_LEN)
    rec = {
        "user": email,
        "wrapped_key": wrapped,
        "wrapped_session": wrapped_session,
        "scope": scope,
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revoked": False,
    }
    _atomic_write(grant_path(root, email), json.dumps(rec, indent=2).encode())
    _atomic_write(kuser_path(root, email), k_user)
    return rec


def add_session(root: str, email: str, wrapped_session: dict) -> dict:
    """Spec 59: session-leg upgrade — add a wrapped refresh token to an
    EXISTING grant (the key was captured earlier; the SSO round-trip now
    yields the session token). Preserves K_user + issued_at. Raises
    GrantError when no grant exists or it is revoked."""
    g = load_grant(root, email)
    if g is None:
        raise GrantError("no grant to upgrade")
    if g.get("revoked"):
        raise GrantError("grant revoked")
    g["wrapped_session"] = wrapped_session
    _atomic_write(grant_path(root, email), json.dumps(g, indent=2).encode())
    return g


def load_grant(root: str, email: str) -> dict | None:
    try:
        with open(grant_path(root, email)) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def status(root: str, email: str) -> dict:
    """Spec 59: {"shared": bool (key grant), "session": bool (session
    token leg present), "usable": bool (BOTH — the only state that may
    render a green pill), "granted_at", "revoked"}"""
    g = load_grant(root, email)
    if g is None:
        return {"shared": False, "session": False, "usable": False,
                "granted_at": None, "revoked": False}
    shared = not g.get("revoked", False)
    session = shared and bool(g.get("wrapped_session"))
    return {
        "shared": shared,
        "session": session,
        "usable": shared and session,
        "granted_at": g.get("issued_at"),
        "revoked": bool(g.get("revoked", False)),
    }


def load_kuser(root: str, email: str) -> bytes:
    """Return the stored wrapping key K_user for the user's grant (for
    wrapping additional payloads like the session leg under the SAME
    key). Raises GrantError when absent/revoked."""
    g = load_grant(root, email)
    if g is None:
        raise GrantError("no grant")
    if g.get("revoked"):
        raise GrantError("grant revoked")
    kpath = kuser_path(root, email)
    if not os.path.exists(kpath):
        raise GrantError("wrapping key missing (revoked?)")
    k_user = open(kpath, "rb").read()
    if len(k_user) != KEY_LEN:
        raise GrantError("bad wrapping key")
    return k_user


def unwrap(root: str, email: str) -> str:
    """Unwrap the stored grant → the user's vault key (b64). Raises
    GrantError on missing/revoked/tampered grants. Plaintext stays in the
    caller's process; never logged."""
    g = load_grant(root, email)
    if g is None:
        raise GrantError("no grant")
    if g.get("revoked"):
        raise GrantError("grant revoked")
    kpath = kuser_path(root, email)
    if not os.path.exists(kpath):
        raise GrantError("wrapping key missing (revoked?)")
    k_user = open(kpath, "rb").read()
    if len(k_user) != KEY_LEN:
        raise GrantError("bad wrapping key")
    w = g.get("wrapped_key") or {}
    try:
        raw = gcm.gcm_decrypt(
            k_user,
            _b64d(w.get("nonce", "")),
            _b64d(w.get("ct", "")),
            _b64d(w.get("tag", "")),
        )
    except (ValueError, TypeError) as e:
        raise GrantError(f"unwrap failed: {e}") from e
    return _b64e(raw)


def unwrap_session(root: str, email: str) -> str:
    """Spec 59: unwrap the stored vault refresh token → plaintext.
    Same failure semantics as unwrap(): missing/revoked/tampered grants
    raise GrantError. Plaintext stays in the caller's process; never
    logged."""
    g = load_grant(root, email)
    if g is None:
        raise GrantError("no grant")
    if g.get("revoked"):
        raise GrantError("grant revoked")
    kpath = kuser_path(root, email)
    if not os.path.exists(kpath):
        raise GrantError("wrapping key missing (revoked?)")
    k_user = open(kpath, "rb").read()
    if len(k_user) != KEY_LEN:
        raise GrantError("bad wrapping key")
    w = g.get("wrapped_session")
    if not w:
        raise GrantError("session leg missing")
    try:
        raw = gcm.gcm_decrypt(
            k_user,
            _b64d(w.get("nonce", "")),
            _b64d(w.get("ct", "")),
            _b64d(w.get("tag", "")),
        )
    except (AssertionError, ValueError, TypeError) as e:
        raise GrantError(f"session unwrap failed: {e}") from e
    return raw.decode("utf-8", "replace")


def revoke(root: str, email: str) -> bool:
    """Revoke the user's grant: mark revoked + delete the wrapping key so
    unwrap fails even if a stale grant.json survives. Returns True if a
    grant existed."""
    g = load_grant(root, email)
    if g is None:
        return False
    g["revoked"] = True
    g["revoked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write(grant_path(root, email), json.dumps(g, indent=2).encode())
    try:
        os.unlink(kuser_path(root, email))
    except OSError:
        pass
    return True


def revoke_all(root: str) -> int:
    """Admin kill switch: revoke every user's grant. Returns count."""
    n = 0
    if not os.path.isdir(root):
        return 0
    for email in sorted(os.listdir(root)):
        if revoke(root, email):
            n += 1
    return n


class GrantError(Exception):
    pass
