#!/usr/bin/env python3
"""Spec 59 consumption proof — runs on the ROUTER container.

Usage: python3 /app/grant-sync.py <email>

Proves the session-token leg end-to-end WITHOUT any user unlock:
  1. unwrap grant (user key, 64B) via granthub
  2. unwrap session leg (vault refresh token) via granthub.unwrap_session
  3. POST /identity/connect/token (grant_type=refresh_token, client web)
     -> fresh access token
  4. GET /api/sync (Bearer) -> encrypted items
  5. decrypt the PowerMail item's login password (AesCbc256_HmacSha256_B64,
     encType 2) with the unwrapped key (encKey = key[0:32], macKey =
     key[32:64]; HMAC-SHA256(macKey, iv||ct) then AES-CBC PKCS7)

FR-9 discipline: prints STATUS ONLY — item name, username, password
length. Never the password, never the tokens, never the key.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, "/app")          # granthub.py
sys.path.insert(0, "/app/vendor")   # pyaes
import granthub  # noqa: E402
from pyaes import AESModeOfOperationCBC, Decrypter  # noqa: E402

GRANT_ROOT = os.environ.get("GRANT_ROOT", "/data/sessions")
VAULT = os.environ.get("VAULT_URL", "https://secrets.pmo.city")
POWERMAIL_ITEM_ID = "1d1dcee2-f6bc-4cdd-98a0-e911e2dd9a72"
POWERMAIL_NAME = "powermail"


def _b64d(s):
    return base64.b64decode(s)


def _decrypt_encstring(enc, key64):
    """Decrypt a Bitwarden EncString (encType 2) with the 64-byte user
    key. Returns plaintext or raises."""
    parts = enc.split(".")
    if len(parts) != 2 or int(parts[0]) != 2:
        raise ValueError(f"unsupported encType {parts[0]}")
    iv, ct, mac = (_b64d(x) for x in parts[1].split("|"))
    enc_key = key64[0:32]
    mac_key = key64[32:64]
    calc = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(calc, mac):
        raise ValueError("MAC mismatch — item tampered or wrong key")
    mode = AESModeOfOperationCBC(enc_key, iv)
    dec = Decrypter(mode)  # PADDING_DEFAULT -> strips PKCS7
    return dec.feed(ct) + dec.feed()


def _post_token(refresh_token):
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": "web",
        "deviceType": "12",
        "deviceIdentifier": "grant-sync-proof",
        "deviceName": "cloudbrowser-broker",
    }).encode()
    req = urllib.request.Request(
        VAULT + "/identity/connect/token", method="POST", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main():
    email = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if not email:
        print("usage: grant-sync.py <email>")
        return 2
    try:
        key_b64 = granthub.unwrap(GRANT_ROOT, email)
        rt = granthub.unwrap_session(GRANT_ROOT, email)
        print(f"grant: key OK ({len(_b64d(key_b64))}B), session leg OK")
    except granthub.GrantError as e:
        print(f"grant FAIL: {e}")
        return 1
    if not rt:
        print("session leg MISSING — grant not usable")
        return 1
    try:
        tok = _post_token(rt)
    except Exception as e:
        print(f"token mint FAIL: {type(e).__name__}: {str(e)[:100]}")
        return 1
    at = tok.get("access_token")
    print("token mint OK: access_token "
          + ("present" if at else "MISSING")
          + f", expires_in={tok.get('expires_in')}s")
    if not at:
        return 1
    try:
        req = urllib.request.Request(
            VAULT + "/api/sync",
            headers={"Authorization": "Bearer " + at,
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            sync = json.loads(r.read().decode())
    except Exception as e:
        print(f"sync FAIL: {type(e).__name__}: {str(e)[:100]}")
        return 1
    # Bitwarden REST /api/sync is FLAT (no "data" wrapper).
    ciphers = sync.get("ciphers") or []
    prof = sync.get("profile") or {}
    print(f"sync OK: {len(ciphers)} cipher(s), profile="
          + str(prof.get("email") or "?")[:60])
    # Refresh-token rotation: Vaultwarden rotates on every mint and
    # revokes the old token. Persist the ROTATED token back into the
    # grant store (wrapped under the same K_user) so the next run works.
    new_rt = tok.get("refresh_token")
    if new_rt:
        try:
            ws, _ = granthub.wrap_bytes(new_rt.encode(),
                                        granthub.load_kuser(GRANT_ROOT, email))
            granthub.add_session(GRANT_ROOT, email, ws)
            print("rotated refresh token persisted back to grant store")
        except Exception as e:
            print(f"WARN: rotated token persist failed: {type(e).__name__}")
    else:
        print("WARN: token response carried no rotated refresh token")
    key64 = _b64d(key_b64)
    target = next((c for c in ciphers
                   if c.get("id") == POWERMAIL_ITEM_ID
                   or POWERMAIL_NAME in (c.get("name") or "").lower()), None)
    if target is None:
        print("PowerMail item NOT FOUND in synced ciphers")
        return 1
    try:
        name = _decrypt_encstring(target.get("name") or "", key64).decode(
            "utf-8", "replace")
    except Exception:
        name = target.get("name") or "?"
    print(f"item: {name} (id {target.get('id')})")
    login = target.get("login") or {}
    user = login.get("username") or ""
    try:
        user = _decrypt_encstring(user, key64).decode("utf-8", "replace")
    except Exception:
        pass
    enc_pwd = login.get("password") or ""
    print(f"username: {user}")
    if not enc_pwd:
        print("password: MISSING")
        return 1
    try:
        pwd = _decrypt_encstring(enc_pwd, key64).decode("utf-8", "replace")
        print(f"password: DECRYPTED OK, length={len(pwd)}")
        print("READ-PATH VERIFIED: broker can mint a session and decrypt "
              "vault items from the stored grant alone.")
        return 0
    except Exception as e:
        print(f"password decrypt FAIL: {type(e).__name__}: {str(e)[:100]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
