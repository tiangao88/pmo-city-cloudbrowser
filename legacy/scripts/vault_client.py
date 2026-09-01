#!/usr/bin/env python3
"""D2 (spec 73) — owner-grant vault client (runs INSIDE the slot).

Reads the CURRENT slot owner's SSO login material from the owner's OWN
GrantHub grant (key + session legs) — spec 68 follow-up "per-user creds
via grant path (D3.4/D2)": no shared files, no sso-creds.json needed.

FR-9: plaintext (user key, refresh token, username, password, TOTP seed)
stays in this process. Callers log status only — never values.
Python 3.9-safe (no X | None annotations).
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.parse
import urllib.request
import fcntl

SLOT_SCRIPTS = os.environ.get("CB_SLOT_SCRIPTS", "/etc/neko/supervisord")
sys.path.insert(0, SLOT_SCRIPTS)                      # gcm.py
sys.path.insert(0, os.path.join(SLOT_SCRIPTS, "vendor"))  # pyaes
import gcm  # noqa: E402
from pyaes import AESModeOfOperationCBC, Decrypter  # noqa: E402

VAULT = os.environ.get("VAULT_URL", "https://secrets.pmo.city")
GRANT_ROOT = os.environ.get("GRANT_ROOT", "/data/sessions")
# Audit B3 (spec 66 isolation): the slot NO LONGER mounts the global
# grant store. Material is fetched from the router's slot-authenticated
# /connect/grant/material endpoint with the slot's OWN bearer
# (CB_SLOT_<n>_TOKEN); the router derives the owner server-side. The
# direct GRANT_ROOT path is kept ONLY as a fallback when no per-slot
# token is configured (legacy local mode, tests).
MATERIAL_URL = os.environ.get("GRANT_MATERIAL_URL",
                              "http://router:8081/connect/grant/material")
GRANT_POST_URL = os.environ.get("GRANT_POST_URL",
                                "http://router:8081/connect/grant")
CB_SLOT_N = int(os.environ.get("CB_SLOT_N", "0") or 0)
CB_SLOT_TOKEN = os.environ.get(f"CB_SLOT_{CB_SLOT_N}_TOKEN", "") if CB_SLOT_N else ""
AUTH_HOSTS = ("auth.aikumi.app", "auth.pmo.city")
DEVICE_NAME = "cloudbrowser-broker"


def _b64d(s):
    return base64.b64decode(s)


def _b64e(b):
    return base64.b64encode(b).decode()


def _fetch_material():
    """(key64_bytes, refresh_token) via the router's slot-authenticated
    endpoint. Server-derived owner — the slot cannot request another
    user's material. Returns None when the per-slot token is unset."""
    if not CB_SLOT_TOKEN:
        return None
    req = urllib.request.Request(
        MATERIAL_URL,
        headers={"Authorization": f"Bearer {CB_SLOT_TOKEN}",
                 "Remote-Email": "", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        j = json.loads(r.read().decode() or "{}")
    key_b64 = j.get("key")
    session = j.get("session")
    if not key_b64 or not session:
        raise RuntimeError("grant material incomplete")
    return _b64d(key_b64), session


def decrypt_encbytes(enc, key64):
    """Decrypt a Bitwarden AES-CBC/HMAC EncString without text decoding.

    This is required for ``profile.privateKey``: it is a binary DER RSA
    private key, so decoding through UTF-8 with replacement would corrupt it.
    Non-EncString input is treated as UTF-8 plaintext for compatibility with
    the text-oriented client fields.
    """
    if not enc:
        return b""
    parts = enc.split(".")
    if len(parts) != 2 or int(parts[0]) != 2:
        return enc.encode("utf-8")
    iv, ct, mac = (_b64d(x) for x in parts[1].split("|"))
    enc_key = key64[0:32]
    mac_key = key64[32:64]
    calc = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(calc, mac):
        raise ValueError("MAC mismatch")
    mode = AESModeOfOperationCBC(enc_key, iv)
    dec = Decrypter(mode)
    return dec.feed(ct) + dec.feed()


def decrypt_encstring(enc, key64):
    """Bitwarden EncString (encType 2) to a text value."""
    return decrypt_encbytes(enc, key64).decode("utf-8", "replace")


def _der_tlv(data, offset=0):
    """Read one DER TLV and return ``(tag, value, next_offset)``."""
    if offset >= len(data):
        raise ValueError("DER truncated tag")
    tag = data[offset]
    offset += 1
    if offset >= len(data):
        raise ValueError("DER truncated length")
    first = data[offset]
    offset += 1
    if first < 0x80:
        length = first
    else:
        nbytes = first & 0x7F
        if nbytes == 0 or nbytes > 4 or offset + nbytes > len(data):
            raise ValueError("DER invalid length")
        length = int.from_bytes(data[offset:offset + nbytes], "big")
        offset += nbytes
    end = offset + length
    if end > len(data):
        raise ValueError("DER value truncated")
    return tag, data[offset:end], end


def _der_children(value):
    children = []
    offset = 0
    while offset < len(value):
        tag, child, offset = _der_tlv(value, offset)
        children.append((tag, child))
    if offset != len(value):
        raise ValueError("DER child boundary")
    return children


def _der_integer(value):
    if not value:
        raise ValueError("DER empty integer")
    if value[0] & 0x80:
        raise ValueError("DER negative integer")
    return int.from_bytes(value, "big")


def _rsa_private_numbers(der):
    """Extract ``(n, d)`` from PKCS#1 or PKCS#8 RSA private-key DER."""
    tag, outer, end = _der_tlv(der, 0)
    if tag != 0x30 or end != len(der):
        raise ValueError("RSA private key is not a DER sequence")
    fields = _der_children(outer)
    if len(fields) >= 9 and fields[0][0] == 0x02 and fields[1][0] == 0x02:
        # PKCS#1 RSAPrivateKey: version, n, e, d, p, q, ...
        return _der_integer(fields[1][1]), _der_integer(fields[3][1])
    if len(fields) >= 3 and fields[0][0] == 0x02:
        # PKCS#8 PrivateKeyInfo: version, AlgorithmIdentifier,
        # OCTET STRING containing the PKCS#1 RSAPrivateKey.
        if fields[1][0] != 0x30 or fields[2][0] != 0x04:
            raise ValueError("unsupported PKCS#8 private key")
        return _rsa_private_numbers(fields[2][1])
    raise ValueError("unsupported RSA private key format")


def _mgf1_sha1(seed, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha1(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:length])


def decrypt_rsa_oaep_sha1_b64(cipher_string, private_der):
    """Decrypt Bitwarden ``4.<base64>`` RSA-OAEP-SHA1 CipherStrings.

    Bitwarden uses encryption type 4 for organization keys in the current
    ``profile.organizations`` sync shape. This implementation is dependency
    free so it remains usable in the slim slot image.
    """
    if not isinstance(cipher_string, str) or not isinstance(private_der, bytes):
        raise ValueError("invalid RSA CipherString inputs")
    parts = cipher_string.split(".")
    if len(parts) != 2 or parts[0] != "4" or not parts[1]:
        raise ValueError("unsupported RSA CipherString")
    try:
        encoded = base64.b64decode(parts[1], validate=True)
    except Exception as exc:
        raise ValueError("invalid RSA CipherString encoding") from exc
    n, d = _rsa_private_numbers(private_der)
    k = (n.bit_length() + 7) // 8
    if len(encoded) != k or k < 2 * 20 + 2:
        raise ValueError("invalid RSA ciphertext length")
    em = pow(int.from_bytes(encoded, "big"), d, n).to_bytes(k, "big")
    if em[0] != 0:
        raise ValueError("RSA OAEP leading byte mismatch")
    masked_seed = em[1:21]
    masked_db = em[21:]
    seed = bytes(a ^ b for a, b in zip(masked_seed, _mgf1_sha1(masked_db, 20)))
    db = bytes(a ^ b for a, b in zip(masked_db, _mgf1_sha1(seed, k - 21)))
    if not hmac.compare_digest(db[:20], hashlib.sha1(b"").digest()):
        raise ValueError("RSA OAEP label hash mismatch")
    rest = db[20:]
    try:
        marker = rest.index(b"\x01")
    except ValueError as exc:
        raise ValueError("RSA OAEP delimiter missing") from exc
    if any(rest[:marker]):
        raise ValueError("RSA OAEP padding mismatch")
    return rest[marker + 1:]


def organization_keys(sync, key64, private_key=None):
    """Resolve organization symmetric keys from old and current sync shapes."""
    org_keys = {}
    legacy = (sync.get("keys") or {}).get("organizationKeys") or []
    if isinstance(legacy, dict):
        legacy = [dict(value, organizationId=oid) if isinstance(value, dict)
                  else {"organizationId": oid, "key": value}
                  for oid, value in legacy.items()]
    for item in legacy:
        try:
            raw = decrypt_encstring(item.get("key") or "", key64)
            org_keys[item.get("organizationId")] = _b64d(raw)
        except Exception:
            pass

    profile = sync.get("profile") or {}
    if private_key is None:
        try:
            private_key = decrypt_encbytes(profile.get("privateKey") or "", key64)
        except Exception:
            private_key = None
    for item in profile.get("organizations") or []:
        oid = item.get("id") or item.get("organizationId")
        try:
            if not oid or not private_key:
                continue
            org_keys[oid] = decrypt_rsa_oaep_sha1_b64(item.get("key") or "", private_key)
        except Exception:
            # Never fall back to the user key for an org cipher: that could
            # produce misleading plaintext. The caller marks it unavailable.
            pass
    return org_keys


def _decrypt_optional(enc, key64):
    try:
        return decrypt_encstring(enc, key64)
    except Exception:
        return ""


def unwrap_grant(user):
    """(key64_bytes, refresh_token) for the CURRENT owner's grant.

    Audit B3: primary path is the router's slot-authenticated material
    endpoint (the slot never mounts the global grant store; the router
    derives the owner server-side and returns only the exact decrypted
    material for THIS slot's owner). Fallback to the direct store only
    when no per-slot token is configured (legacy local mode)."""
    m = _fetch_material()
    if m is not None:
        return m
    gdir = os.path.join(GRANT_ROOT, user, "grant")
    with open(os.path.join(gdir, "grant.json")) as f:
        g = json.load(f)
    if g.get("revoked"):
        raise RuntimeError("grant revoked")
    with open(os.path.join(gdir, "k_user.bin"), "rb") as f:
        k_user = f.read()
    if len(k_user) != 32:
        raise RuntimeError("bad wrapping key")

    def unwrap(payload):
        return gcm.gcm_decrypt(k_user, _b64d(payload["nonce"]),
                               _b64d(payload["ct"]), _b64d(payload["tag"]))

    key64 = unwrap(g["wrapped_key"])
    if len(key64) != 64:
        raise RuntimeError("bad user key length")
    if not g.get("wrapped_session"):
        raise RuntimeError("no session leg")
    rt = unwrap(g["wrapped_session"]).decode()
    return key64, rt


def _mint(rt, device_id):
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": rt,
        "client_id": "web", "deviceType": "12",
        "deviceIdentifier": device_id, "deviceName": DEVICE_NAME,
    }).encode()
    req = urllib.request.Request(
        VAULT + "/identity/connect/token", method="POST", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


class RefreshRotationPersistenceError(RuntimeError):
    pass


def _persist_rotated(user, new_rt):
    """Persist a remotely rotated refresh token or fail loudly.

    Returning success while persistence failed would hand out an access token
    backed by a now-lost refresh leg. Atomic replacement is mandatory.
    """
    gdir = os.path.join(GRANT_ROOT, user, "grant")
    with open(os.path.join(gdir, "k_user.bin"), "rb") as f:
        k_user = f.read()
    iv = os.urandom(12)
    ct, tag = gcm.gcm_encrypt(k_user, iv, new_rt.encode())
    with open(os.path.join(gdir, "grant.json")) as f:
        g = json.load(f)
    g["wrapped_session"] = {"nonce": _b64e(iv), "ct": _b64e(ct),
                            "tag": _b64e(tag)}
    tmp = os.path.join(gdir, "grant.json.tmp.%d" % os.getpid())
    try:
        with open(tmp, "w") as f:
            json.dump(g, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, os.path.join(gdir, "grant.json"))
    except Exception as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RefreshRotationPersistenceError("rotated session could not be persisted") from exc
    return True


def _persist_rotated_router(new_rt):
    req = urllib.request.Request(
        GRANT_POST_URL, method="POST",
        data=json.dumps({"session": new_rt}).encode(),
        headers={"Authorization": "Bearer " + CB_SLOT_TOKEN,
                 "Content-Type": "application/json", "Remote-Email": ""})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status != 200:
                raise RuntimeError("grant update rejected")
    except Exception as exc:
        raise RefreshRotationPersistenceError(
            "router rejected rotated session persistence") from exc


def mint_access_token(user, device_id="vault-client"):
    """Mint under a cross-process owner lock covering read→mint→persist.

    In per-slot router-material mode only one broker process exists for the
    owner; persistence is performed by the router capture path. Legacy direct
    store mode uses flock so rotating refresh tokens cannot be consumed twice.
    """
    if CB_SLOT_TOKEN:
        key64, rt = unwrap_grant(user)
        tok = _mint(rt, device_id)
        if tok.get("refresh_token"):
            _persist_rotated_router(tok["refresh_token"])
        return key64, tok
    gdir = os.path.join(GRANT_ROOT, user, "grant")
    os.makedirs(gdir, exist_ok=True)
    with open(os.path.join(gdir, ".refresh.lock"), "a+") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        key64, rt = unwrap_grant(user)
        tok = _mint(rt, device_id)
        if tok.get("refresh_token"):
            _persist_rotated(user, tok["refresh_token"])
        return key64, tok


def sync_ciphers(user, device_id="vault-client"):
    """GET /api/sync with a freshly minted token → (key64_bytes, sync)."""
    key64, tok = mint_access_token(user, device_id)
    at = tok.get("access_token")
    if not at:
        raise RuntimeError("no access token")
    req = urllib.request.Request(
        VAULT + "/api/sync",
        headers={"Authorization": "Bearer " + at, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return key64, json.loads(r.read().decode())


def login_items(user, device_id="vault-client"):
    """All LOGIN ciphers as decrypted views (values in-process only):

    [{id, name, uris, username, password, totp_secret,
      org_key_missing}] — org items decrypted with the org key when the
    sync delivers it; otherwise flagged org_key_missing (never a wrong
    decrypt)."""
    key64, sync = sync_ciphers(user, device_id)
    org_keys = organization_keys(sync, key64)
    items = []
    for c in sync.get("ciphers") or []:
        if c.get("type") != 1:  # login
            continue
        org_id = c.get("organizationId")
        org_key = org_keys.get(org_id)
        key_use = org_key if org_key else key64
        login = c.get("login") or {}
        uris = []
        for ent in login.get("uris") or []:
            u = _decrypt_optional(ent.get("uri") or "", key_use)
            if u:
                uris.append(u)
        items.append({
            "id": c.get("id"),
            "name": _decrypt_optional(c.get("name") or "", key_use),
            "uris": uris,
            "username": _decrypt_optional(login.get("username") or "", key_use),
            "password": _decrypt_optional(login.get("password") or "", key_use),
            "totp_secret": totp_secret(c, key_use),
            "org_key_missing": bool(org_id and not org_key),
        })
    return items


def totp_secret(item, key_use=None):
    """The item's TOTP seed: native login.totp first, else a custom field
    named TOTP/totp. None when absent. Never logged by callers."""
    login = (item.get("login") or {}) if isinstance(item, dict) else {}
    raw = login.get("totp")
    if raw:
        if key_use is not None:
            try:
                return decrypt_encstring(raw, key_use)
            except Exception:
                pass
        elif isinstance(raw, str):
            return raw
    for f in item.get("fields") or []:
        fname = f.get("name") or ""
        if key_use is not None:
            try:
                fname = decrypt_encstring(fname, key_use)
            except Exception:
                pass
        if str(fname).strip().upper() == "TOTP":
            val = f.get("value") or ""
            if key_use is not None:
                try:
                    return decrypt_encstring(val, key_use)
                except Exception:
                    return None
            return val or None
    return None


class VaultItemSelectionError(RuntimeError):
    pass


def _allowed_auth_uri(raw):
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (parsed.scheme == "https" and parsed.hostname in AUTH_HOSTS
            and port in (None, 443) and parsed.username is None
            and parsed.password is None)


def find_ssologin(items, item_id=None, exact_name="Authentik Spike User"):
    """Select exactly one configured SSO cipher and validate its auth URI.

    An immutable cipher id is authoritative when configured; otherwise the
    decrypted item name must match exactly. Zero/duplicate/deceptive matches
    fail closed rather than selecting the first item.
    """
    if item_id:
        matches = [it for it in items if it.get("id") == item_id]
    else:
        matches = [it for it in items if it.get("name") == exact_name]
    if len(matches) != 1:
        raise VaultItemSelectionError("expected exactly one configured SSO cipher")
    selected = matches[0]
    if not any(_allowed_auth_uri(u) for u in (selected.get("uris") or [])):
        raise VaultItemSelectionError("configured SSO cipher has no allowed HTTPS URI")
    return selected
