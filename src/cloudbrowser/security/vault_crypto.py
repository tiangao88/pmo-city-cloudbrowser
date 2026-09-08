"""Vaultwarden cipher crypto for the credential broker (broker-only path).

Implements the subset of the Bitwarden/Vaultwarden vault format needed to
decrypt login ciphers after a per-call unlock:

- encString/encBuffer type 2 (AesCbc256_HmacSha256_B64) decrypt/encrypt;
- RSA-2048 OAEP unwrap for organization keys (encString types 4/5/6);
- AES-256-GCM encrypt/decrypt (prior-generation grant envelopes, NIST
  SP 800-38D);
- Bitwarden key derivation: PBKDF2-SHA256 master key, HKDF-Expand
  stretching to (enc_key, mac_key).

Anything else fails closed: unknown encString types raise
``UnsupportedCipherType`` instead of guessing. Plaintext material exists
only inside the broker process; nothing here logs or serializes key bytes.

All primitives run on the host OpenSSL (``libcrypto.so.3``) through
ctypes — no new package dependencies (python:3.12-slim ships libcrypto
for the ssl module). Known-answer tests pin NIST GCM vectors, CBC round
trips, and MAC-failure behavior in ``tests/unit/test_vault_crypto.py``.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac as hmac_mod
import json
import os
from ctypes import (
    POINTER,
    byref,
    c_char_p,
    c_int,
    c_size_t,
    c_ubyte,
    c_void_p,
    create_string_buffer,
)
from dataclasses import dataclass
from typing import Mapping

# OpenSSL EVP control codes (openssl/evp.h) and padding flag.
EVP_CTRL_GCM_SET_IVLEN = 0x9
EVP_CTRL_GCM_GET_TAG = 0x10
EVP_CTRL_GCM_SET_TAG = 0x11
RSA_PKCS1_OAEP_PADDING = 1

_LIB = None


def _lib():
    global _LIB
    if _LIB is not None:
        return _LIB
    last: OSError | None = None
    for candidate in ("libcrypto.so.3", "libcrypto.so"):
        try:
            _LIB = ctypes.CDLL(candidate)
            break
        except OSError as exc:  # pragma: no cover - platform dependent
            last = exc
    if _LIB is None:
        raise RuntimeError(f"OpenSSL libcrypto is required for vault crypto: {last}")
    lib = _LIB
    lib.EVP_CIPHER_CTX_new.restype = c_void_p
    lib.EVP_CIPHER_CTX_free.argtypes = [c_void_p]
    for name in (
        "EVP_aes_256_gcm",
        "EVP_aes_128_gcm",
        "EVP_aes_128_cbc",
        "EVP_aes_256_cbc",
        "EVP_sha1",
        "EVP_sha256",
    ):
        getattr(lib, name).restype = c_void_p
    for name in ("EVP_EncryptInit_ex", "EVP_DecryptInit_ex"):
        fn = getattr(lib, name)
        fn.restype = c_int
        fn.argtypes = [c_void_p, c_void_p, c_void_p, c_char_p, c_char_p]
    for name in ("EVP_EncryptUpdate", "EVP_DecryptUpdate"):
        fn = getattr(lib, name)
        fn.restype = c_int
        fn.argtypes = [c_void_p, c_void_p, POINTER(c_int), c_void_p, c_int]
    for name in ("EVP_EncryptFinal_ex", "EVP_DecryptFinal_ex"):
        fn = getattr(lib, name)
        fn.restype = c_int
        fn.argtypes = [c_void_p, c_void_p, POINTER(c_int)]
    lib.EVP_CIPHER_CTX_ctrl.restype = c_int
    lib.EVP_CIPHER_CTX_ctrl.argtypes = [c_void_p, c_int, c_int, c_void_p]
    lib.EVP_PKEY_free.argtypes = [c_void_p]
    lib.d2i_AutoPrivateKey.restype = c_void_p
    lib.d2i_AutoPrivateKey.argtypes = [POINTER(c_void_p), POINTER(POINTER(c_ubyte)), c_int]
    lib.EVP_PKEY_CTX_new.restype = c_void_p
    lib.EVP_PKEY_CTX_new.argtypes = [c_void_p, c_void_p]
    lib.EVP_PKEY_CTX_free.argtypes = [c_void_p]
    return _LIB


class VaultCryptoError(RuntimeError):
    """Base error: verification failures, bad input, OpenSSL failures."""


class MacVerificationFailed(VaultCryptoError):
    """Ciphertext MAC/tag did not verify — wrong key or tampered input."""


class UnsupportedCipherType(VaultCryptoError):
    """EncString type outside the supported subset (fail closed)."""


# ---------------------------------------------------------------------------
# AES via OpenSSL EVP
# ---------------------------------------------------------------------------


def _update(ctx, data: bytes, *, encrypt: bool) -> bytes:
    lib = _lib()
    out = create_string_buffer(len(data) + 16)
    outlen = c_int()
    update = lib.EVP_EncryptUpdate if encrypt else lib.EVP_DecryptUpdate
    if update(ctx, out, byref(outlen), data, len(data)) != 1:
        raise VaultCryptoError("cipher update failed")
    return out.raw[: outlen.value]


def _final(ctx, *, encrypt: bool) -> bytes:
    lib = _lib()
    out = create_string_buffer(16)
    outlen = c_int()
    final = lib.EVP_EncryptFinal_ex if encrypt else lib.EVP_DecryptFinal_ex
    if final(ctx, out, byref(outlen)) != 1:
        if not encrypt:
            raise MacVerificationFailed("final decrypt failed (padding/tag)")
        raise VaultCryptoError("final encrypt failed")
    return out.raw[: outlen.value]


def _init_cipher(ctx, cipher, key: bytes, iv: bytes, *, encrypt: bool) -> None:
    lib = _lib()
    init = lib.EVP_EncryptInit_ex if encrypt else lib.EVP_DecryptInit_ex
    if init(ctx, cipher, None, key, iv) != 1:
        raise VaultCryptoError("cipher init failed")


def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """AES-CBC with PKCS#7 padding (OpenSSL default). IV must be 16 bytes."""
    if len(iv) != 16:
        raise VaultCryptoError("CBC IV must be 16 bytes")
    if len(key) not in (16, 24, 32):
        raise VaultCryptoError("AES key must be 16/24/32 bytes")
    lib = _lib()
    cipher = lib.EVP_aes_256_cbc() if len(key) == 32 else lib.EVP_aes_128_cbc()
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise VaultCryptoError("EVP_CIPHER_CTX_new failed")
    try:
        _init_cipher(ctx, cipher, key, iv, encrypt=True)
        return _update(ctx, plaintext, encrypt=True) + _final(ctx, encrypt=True)
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


def aes_cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    if len(iv) != 16:
        raise VaultCryptoError("CBC IV must be 16 bytes")
    if len(key) not in (16, 24, 32):
        raise VaultCryptoError("AES key must be 16/24/32 bytes")
    lib = _lib()
    cipher = lib.EVP_aes_256_cbc() if len(key) == 32 else lib.EVP_aes_128_cbc()
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise VaultCryptoError("EVP_CIPHER_CTX_new failed")
    try:
        _init_cipher(ctx, cipher, key, iv, encrypt=False)
        return _update(ctx, ciphertext, encrypt=False) + _final(ctx, encrypt=False)
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


def _gcm_ctx(key: bytes, iv: bytes, *, encrypt: bool) -> c_void_p:
    lib = _lib()
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise VaultCryptoError("EVP_CIPHER_CTX_new failed")
    cipher = lib.EVP_aes_128_gcm() if len(key) == 16 else lib.EVP_aes_256_gcm()
    init = lib.EVP_EncryptInit_ex if encrypt else lib.EVP_DecryptInit_ex
    if init(ctx, cipher, None, None, None) != 1:
        lib.EVP_CIPHER_CTX_free(ctx)
        raise VaultCryptoError("GCM init (cipher) failed")
    if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(iv), None) != 1:
        lib.EVP_CIPHER_CTX_free(ctx)
        raise VaultCryptoError("GCM set IV length failed")
    if init(ctx, None, None, key, iv) != 1:
        lib.EVP_CIPHER_CTX_free(ctx)
        raise VaultCryptoError("GCM init (key/iv) failed")
    return ctx


def aes_gcm_encrypt(key: bytes, iv: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
    """AES-GCM encrypt (128/256-bit key); returns (ciphertext, 16-byte tag)."""
    if len(key) not in (16, 32):
        raise VaultCryptoError("GCM key must be 16 or 32 bytes")
    if not 1 <= len(iv) <= 255:
        raise VaultCryptoError("GCM IV length must be 1..255 bytes")
    lib = _lib()
    ctx = _gcm_ctx(key, iv, encrypt=True)
    try:
        if aad:
            n = c_int()
            if lib.EVP_EncryptUpdate(ctx, None, byref(n), aad, len(aad)) != 1:
                raise VaultCryptoError("GCM AAD update failed")
        ct = _update(ctx, plaintext, encrypt=True) + _final(ctx, encrypt=True)
        tagbuf = create_string_buffer(16)
        n = c_int()
        if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, 16, tagbuf) != 1:
            raise VaultCryptoError("GCM get tag failed")
        _ = n
        return ct, tagbuf.raw[:16]
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


def aes_gcm_decrypt(key: bytes, iv: bytes, ciphertext: bytes, tag: bytes, aad: bytes = b"") -> bytes:
    """AES-GCM decrypt (128/256-bit key); raises MacVerificationFailed on tag mismatch."""
    if len(key) not in (16, 32):
        raise VaultCryptoError("GCM key must be 16 or 32 bytes")
    if len(tag) != 16:
        raise VaultCryptoError("GCM tag must be 16 bytes")
    lib = _lib()
    ctx = _gcm_ctx(key, iv, encrypt=False)
    try:
        if aad:
            n = c_int()
            if lib.EVP_DecryptUpdate(ctx, None, byref(n), aad, len(aad)) != 1:
                raise VaultCryptoError("GCM AAD update failed")
        pt = _update(ctx, ciphertext, encrypt=False)
        tagbuf = create_string_buffer(16)
        ctypes.memmove(tagbuf, tag, 16)
        if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, 16, tagbuf) != 1:
            raise VaultCryptoError("GCM set tag failed")
        return pt + _final(ctx, encrypt=False)
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


# ---------------------------------------------------------------------------
# RSA-OAEP via OpenSSL (organization key unwrap)
# ---------------------------------------------------------------------------


def _load_evp_private_key(der: bytes) -> c_void_p:
    lib = _lib()
    buf = create_string_buffer(der, len(der))
    ptr = c_void_p()
    cur = ctypes.cast(buf, POINTER(c_ubyte))
    key = lib.d2i_AutoPrivateKey(byref(ptr), byref(cur), len(der))
    if not key:
        raise VaultCryptoError("could not parse private key DER")
    return key


def rsa_oaep_decrypt(der_private_key: bytes, ciphertext: bytes, *, sha256: bool = True) -> bytes:
    """RSA-OAEP decrypt with an in-memory PKCS#1/PKCS#8 DER private key."""
    lib = _lib()
    evp_key = _load_evp_private_key(der_private_key)
    try:
        ctx = lib.EVP_PKEY_CTX_new(evp_key, None)
        if not ctx:
            raise VaultCryptoError("EVP_PKEY_CTX_new failed")
        try:
            if lib.EVP_PKEY_decrypt_init(ctx) != 1:
                raise VaultCryptoError("decrypt init failed")
            lib.EVP_PKEY_CTX_set_rsa_padding.argtypes = [c_void_p, c_int]
            if lib.EVP_PKEY_CTX_set_rsa_padding(ctx, RSA_PKCS1_OAEP_PADDING) != 1:
                raise VaultCryptoError("set OAEP padding failed")
            md = lib.EVP_sha256() if sha256 else lib.EVP_sha1()
            set_oaep_md = getattr(lib, "EVP_PKEY_CTX_set_rsa_oaep_md", None)
            if set_oaep_md is None:  # pragma: no cover - ancient OpenSSL
                raise VaultCryptoError("OpenSSL lacks EVP_PKEY_CTX_set_rsa_oaep_md")
            set_oaep_md.argtypes = [c_void_p, c_void_p]
            if set_oaep_md(ctx, md) != 1:
                raise VaultCryptoError("set OAEP md failed")
            lib.EVP_PKEY_CTX_set_rsa_mgf1_md.argtypes = [c_void_p, c_void_p]
            if lib.EVP_PKEY_CTX_set_rsa_mgf1_md(ctx, md) != 1:
                raise VaultCryptoError("set MGF1 md failed")
            lib.EVP_PKEY_decrypt.argtypes = [
                c_void_p, c_char_p, POINTER(c_size_t), c_char_p, c_size_t
            ]
            outlen = c_size_t()
            if lib.EVP_PKEY_decrypt(ctx, None, byref(outlen), ciphertext, len(ciphertext)) != 1:
                raise VaultCryptoError("decrypt size query failed")
            out = create_string_buffer(max(int(outlen.value), 1))
            if lib.EVP_PKEY_decrypt(ctx, out, byref(outlen), ciphertext, len(ciphertext)) != 1:
                raise MacVerificationFailed("RSA decrypt failed")
            return out.raw[: outlen.value]
        finally:
            lib.EVP_PKEY_CTX_free(ctx)
    finally:
        lib.EVP_PKEY_free(evp_key)


# ---------------------------------------------------------------------------
# Bitwarden key derivation
# ---------------------------------------------------------------------------


def hkdf_expand(key: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF-Expand (Bitwarden key stretching uses this directly)."""
    out = b""
    t = b""
    counter = 1
    while len(out) < length:
        t = hmac_mod.new(key, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]


def stretch_to_enc_mac(key64: bytes) -> tuple[bytes, bytes]:
    """64-byte symmetric key -> (enc_key 32, mac_key 32) (Bitwarden layout)."""
    if len(key64) != 64:
        raise VaultCryptoError("symmetric keys must be 64 bytes (32 enc + 32 mac)")
    return key64[:32], key64[32:]


def master_key(password: str, email: str, iterations: int) -> bytes:
    """PBKDF2-SHA256 master key from the account password + lowercased email."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), email.strip().lower().encode(), iterations
    )


def stretched_master_key(password: str, email: str, iterations: int) -> tuple[bytes, bytes]:
    """(enc, mac) keys for unwrapping the profile user key (HKDF stretch)."""
    mk = master_key(password, email, iterations)
    stretched = hkdf_expand(mk, b"enc") + hkdf_expand(mk, b"mac")
    return stretch_to_enc_mac(stretched)


# ---------------------------------------------------------------------------
# Bitwarden encString / encBuffer format
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EncString:
    """Parsed Bitwarden encString: ``<type>.<body>``."""

    type: int
    iv: bytes
    ct: bytes
    mac: bytes | None

    @classmethod
    def parse(cls, raw: str | bytes) -> "EncString":
        text = raw.decode() if isinstance(raw, bytes) else raw
        if not text or "." not in text:
            raise VaultCryptoError("malformed encString")
        head, _, rest = text.partition(".")
        try:
            enc_type = int(head)
        except ValueError as exc:
            raise VaultCryptoError("malformed encString type") from exc
        if enc_type == 2:
            iv_b64, _, remainder = rest.partition("|")
            ct_b64, _, mac_b64 = remainder.partition("|")
            if not iv_b64 or not ct_b64 or not mac_b64:
                raise VaultCryptoError("malformed encString body")
            try:
                return cls(
                    2,
                    base64.b64decode(iv_b64),
                    base64.b64decode(ct_b64),
                    base64.b64decode(mac_b64),
                )
            except Exception as exc:
                raise VaultCryptoError("malformed encString base64") from exc
        if enc_type in (4, 5, 6):
            # RSA-wrapped key material: single base64 body, no MAC.
            try:
                return cls(enc_type, b"", base64.b64decode(rest), None)
            except Exception as exc:
                raise VaultCryptoError("malformed RSA encString base64") from exc
        raise UnsupportedCipherType(f"encString type {enc_type} is not supported")


def _decrypt_type2_raw(enc: EncString, key64: bytes) -> bytes:
    enc_key, mac_key = stretch_to_enc_mac(key64)
    expected = hmac_mod.new(mac_key, enc.iv + enc.ct, hashlib.sha256).digest()
    if enc.mac is None or not hmac_mod.compare_digest(expected, enc.mac):
        raise MacVerificationFailed("encString MAC mismatch")
    return aes_cbc_decrypt(enc_key, enc.iv, enc.ct)


def decrypt_encstring_bytes(raw: str | bytes, key64: bytes) -> bytes:
    """Decrypt a type-2 encString to raw bytes (key material)."""
    enc = EncString.parse(raw)
    if enc.type != 2:
        raise UnsupportedCipherType(f"type {enc.type} is not symmetric encString")
    return _decrypt_type2_raw(enc, key64)


def decrypt_encstring(raw: str | bytes, key64: bytes) -> str:
    """Decrypt a type-2 encString as UTF-8 text (names, usernames, URIs)."""
    return decrypt_encstring_bytes(raw, key64).decode("utf-8")


def encrypt_encstring(plaintext: str, key64: bytes) -> str:
    """Encrypt to a type-2 encString (tests and grant-envelope rewrap)."""
    enc_key, mac_key = stretch_to_enc_mac(key64)
    iv = os.urandom(16)
    ct = aes_cbc_encrypt(enc_key, iv, plaintext.encode("utf-8"))
    mac = hmac_mod.new(mac_key, iv + ct, hashlib.sha256).digest()
    return "2.{}|{}|{}".format(
        base64.b64encode(iv).decode(),
        base64.b64encode(ct).decode(),
        base64.b64encode(mac).decode(),
    )


def rsa_decrypt_encstring(raw: str | bytes, der_private_key: bytes, *, sha256: bool = True) -> bytes:
    """Unwrap an RSA-encapsulated key (encString types 4/5/6)."""
    enc = EncString.parse(raw)
    if enc.type not in (4, 5, 6):
        raise UnsupportedCipherType(f"type {enc.type} is not RSA-wrapped")
    return rsa_oaep_decrypt(der_private_key, enc.ct, sha256=sha256)


# ---------------------------------------------------------------------------
# Prior-generation grant-envelope compatibility (AES-GCM JSON wrapping)
# ---------------------------------------------------------------------------


def unwrap_grant_envelope(envelope: Mapping[str, bytes], wrapping_key: bytes) -> tuple[bytes, bytes]:
    """Decrypt a prior-generation grant envelope {nonce, ct, tag} (GCM).

    Returns the (wrapped_key_leg, session_leg) payload only when the tag
    verifies and the payload is the expected 64-byte two-leg layout;
    otherwise raises MacVerificationFailed / VaultCryptoError.
    """
    payload = aes_gcm_decrypt(
        wrapping_key, envelope["nonce"], envelope["ct"], envelope["tag"]
    )
    if len(payload) != 64:
        raise VaultCryptoError("unexpected grant payload length")
    return payload[:32], payload[32:]


def json_sanitize(obj: object) -> str:
    """Helper for audit-side serialization of non-secret metadata."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
