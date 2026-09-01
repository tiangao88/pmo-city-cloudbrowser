#!/usr/bin/env python3
"""D2 (spec 73) — deterministic RFC 6238 TOTP (pure stdlib, 3.9-safe).

The broker computes 2FA codes ONLY from a stored seed (FR-5 Q3 hybrid):
this module is deterministic — no network, no LLM, no logging of codes.

Public API:
  normalize_secret(raw) -> str   # base32 uppercase, otpauth:// aware
  totp(secret, at=None, step=30, digits=6, algo="sha1") -> str
"""
import base64
import hashlib
import hmac
import re
import struct
import time

_STEP = 30
_DIGITS = 6

_OTPAUTH_RE = re.compile(r"^otpauth://(?:totp|hotp)/[^?]*\?(.*)$", re.I)
_B32_CLEAN = re.compile(r"[^A-Z2-7]")


def normalize_secret(raw):
    """Return the canonical secret from a raw value.

    Accepts: an otpauth:// URL (secret query param), base32 (spaces/
    lowercase tolerated), or any other string (returned uppercased
    stripped, unchanged alphabet). Never raises; never logs the value.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    m = _OTPAUTH_RE.match(s)
    if m:
        params = {}
        for pair in m.group(1).split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k.lower()] = v
        s = params.get("secret", "")
    s = s.upper().replace(" ", "")
    # Only treat as base32 when the string is pure base32 alphabet;
    # otherwise it is a raw secret and must pass through unchanged
    # (some TOTP issuers use arbitrary strings).
    cleaned = _B32_CLEAN.sub("", s)
    if cleaned == s and s:
        if len(s) % 8 != 0:
            s += "=" * (8 - (len(s) % 8))
        return s
    return s if s else cleaned


def _counter_bytes(at, step):
    counter = int(at) // int(step)
    return struct.pack(">Q", counter)


def _hotp(secret_bytes, counter, digits, algo):
    h = hmac.new(secret_bytes, _counter_bytes(counter, 1), getattr(hashlib, algo))
    digest = h.digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp(secret, at=None, step=_STEP, digits=_DIGITS, algo="sha1"):
    """RFC 6238 TOTP for the given secret (base32). `at` is injectable
    (unix seconds) for deterministic tests; defaults to time.time()."""
    if at is None:
        at = time.time()
    b32 = normalize_secret(secret)
    if not b32:
        raise ValueError("empty TOTP secret")
    try:
        secret_bytes = base64.b32decode(b32)
    except Exception:
        # non-base32 fallback: use the raw bytes of the canonical string
        secret_bytes = b32.encode("ascii")
    return _hotp(secret_bytes, int(at) // step, digits, algo)
