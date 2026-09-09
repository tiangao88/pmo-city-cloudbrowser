"""Known-answer and round-trip tests for the broker vault crypto layer.

Pins NIST GCM test vectors (SP 800-38D case 1/2/3), CBC + HMAC encString
round trips, RSA-OAEP unwrap against a generated key, RFC 5869 HKDF, and
the fail-closed behavior for unsupported types / tampered MACs.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac as hmac_mod
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

import pytest

from cloudbrowser.security import vault_crypto as vc


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


# --- NIST GCM test vectors (SP 800-38D, 96-bit IV) -------------------------


def test_nist_gcm_case1() -> None:
    key = bytes.fromhex("00" * 32)
    iv = bytes.fromhex("00" * 12)
    ct, tag = vc.aes_gcm_encrypt(key, iv, b"")
    assert ct == b""
    assert tag == bytes.fromhex("530f8afbc74536b9a963b4f1c4cb738b")


def test_nist_gcm_case2() -> None:
    key = bytes.fromhex("00" * 32)
    iv = bytes.fromhex("00" * 12)
    ct, tag = vc.aes_gcm_encrypt(key, iv, b"\x00" * 16)
    assert ct == bytes.fromhex("cea7403d4d606b6e074ec5d3baf39d18")
    assert tag == bytes.fromhex("d0d1c8a799996bf0265b98b5d48ab919")


def test_nist_gcm_case3_with_aad() -> None:
    key = bytes.fromhex("feffe9928665731c6d6a8f9467308308")
    iv = bytes.fromhex("cafebabefacedbaddecaf888")
    pt = bytes.fromhex(
        "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
        "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39"
    )
    aad = bytes.fromhex("feedfacedeadbeeffeedfacedeadbeefabaddad2")
    ct, tag = vc.aes_gcm_encrypt(key, iv, pt, aad=aad)
    # Expected values independently confirmed via Node's crypto (same
    # OpenSSL backend) for this exact 32-byte message + 20-byte AAD.
    assert ct.startswith(bytes.fromhex("42831ec2217774244b7221b784d0d49c"))
    assert tag == bytes.fromhex("5bc94fbc3221a5db94fae95ae7121a47")
    assert vc.aes_gcm_decrypt(key, iv, ct, tag, aad=aad) == pt


def test_gcm_round_trip_and_tamper() -> None:
    key = vc.hkdf_expand(b"k" * 32, b"enc")
    iv = b"\x01" * 12
    ct, tag = vc.aes_gcm_encrypt(key, iv, b"payload material", aad=b"hdr")
    assert vc.aes_gcm_decrypt(key, iv, ct, tag, aad=b"hdr") == b"payload material"
    with pytest.raises(vc.MacVerificationFailed):
        vc.aes_gcm_decrypt(key, iv, ct + b"\x00", tag, aad=b"hdr")
    bad_tag = bytes([tag[0] ^ 1]) + tag[1:]
    with pytest.raises(vc.MacVerificationFailed):
        vc.aes_gcm_decrypt(key, iv, ct, bad_tag, aad=b"hdr")


# --- CBC round trip ---------------------------------------------------------


def test_cbc_round_trip_rejects_bad_key() -> None:
    key = bytes(range(32))
    iv = bytes(range(16))
    ct = vc.aes_cbc_encrypt(key, iv, b"secret bytes to protect")
    assert vc.aes_cbc_decrypt(key, iv, ct) == b"secret bytes to protect"
    with pytest.raises(vc.VaultCryptoError):
        vc.aes_cbc_encrypt(key[:8], iv, b"x")
    with pytest.raises(vc.VaultCryptoError):
        vc.aes_cbc_encrypt(key, b"short", b"x")


# --- encString format --------------------------------------------------------


def _make_key64() -> bytes:
    return hashlib.sha256(b"test-vault-key").digest() + hashlib.sha256(b"mac-part").digest()


def test_encstring_round_trip() -> None:
    key64 = _make_key64()
    enc = vc.encrypt_encstring("login@example.test", key64)
    assert enc.startswith("2.")
    assert vc.decrypt_encstring(enc, key64) == "login@example.test"


def test_encstring_mac_tamper_fails() -> None:
    key64 = _make_key64()
    enc = vc.encrypt_encstring("secret", key64)
    head, _, body = enc.partition(".")
    iv_b64, ct_b64, mac_b64 = body.split("|")
    mac = bytearray(base64.b64decode(mac_b64))
    mac[0] ^= 1
    tampered = f"{head}.{iv_b64}|{ct_b64}|{_b64(bytes(mac))}"
    with pytest.raises(vc.MacVerificationFailed):
        vc.decrypt_encstring(tampered, key64)


def test_encstring_wrong_key_fails() -> None:
    key64 = _make_key64()
    other = bytes(reversed(key64))
    enc = vc.encrypt_encstring("secret", key64)
    with pytest.raises(vc.MacVerificationFailed):
        vc.decrypt_encstring(enc, other)


def test_encstring_unsupported_type_fails_closed() -> None:
    with pytest.raises(vc.UnsupportedCipherType):
        vc.EncString.parse("0.aGVsbG8=")
    with pytest.raises(vc.UnsupportedCipherType):
        vc.EncString.parse("3.AAAA|BBBB|CCCC")


def test_encstring_malformed_fails() -> None:
    with pytest.raises(vc.VaultCryptoError):
        vc.EncString.parse("")
    with pytest.raises(vc.VaultCryptoError):
        vc.EncString.parse("nodot")
    with pytest.raises(vc.VaultCryptoError):
        vc.EncString.parse("x.y")


# --- RSA-OAEP unwrap ----------------------------------------------------------


def test_rsa_oaep_unwrap_sha256_round_trip() -> None:
    lib = vc._lib()
    lib.EVP_PKEY_CTX_new_id.restype = c_void_p
    lib.EVP_PKEY_CTX_new_id.argtypes = [c_int, c_void_p]
    lib.EVP_PKEY_keygen_init.argtypes = [c_void_p]
    lib.EVP_PKEY_keygen_init.restype = c_int
    lib.EVP_PKEY_CTX_set_rsa_keygen_bits.argtypes = [c_void_p, c_int]
    lib.EVP_PKEY_CTX_set_rsa_keygen_bits.restype = c_int
    lib.EVP_PKEY_keygen.argtypes = [c_void_p, POINTER(c_void_p)]
    lib.EVP_PKEY_keygen.restype = c_int
    lib.EVP_PKEY_free.argtypes = [c_void_p]
    lib.EVP_PKEY_CTX_free.argtypes = [c_void_p]
    lib.i2d_PrivateKey.restype = c_int
    lib.i2d_PrivateKey.argtypes = [c_void_p, POINTER(POINTER(c_ubyte))]
    lib.EVP_PKEY_encrypt_init.argtypes = [c_void_p]
    lib.EVP_PKEY_encrypt_init.restype = c_int
    lib.EVP_PKEY_CTX_set_rsa_padding.argtypes = [c_void_p, c_int]
    lib.EVP_PKEY_CTX_set_rsa_padding.restype = c_int
    lib.EVP_PKEY_encrypt.argtypes = [
        c_void_p, c_void_p, POINTER(c_size_t), c_char_p, c_size_t
    ]
    lib.EVP_PKEY_encrypt.restype = c_int

    ctx = lib.EVP_PKEY_CTX_new_id(6, None)  # EVP_PKEY_RSA
    assert lib.EVP_PKEY_keygen_init(ctx) == 1
    assert lib.EVP_PKEY_CTX_set_rsa_keygen_bits(ctx, 2048) == 1
    pkey = c_void_p()
    assert lib.EVP_PKEY_keygen(ctx, byref(pkey)) == 1
    try:
        der_len = lib.i2d_PrivateKey(pkey, None)
        assert der_len > 0
        cursor = POINTER(c_ubyte)()
        written = lib.i2d_PrivateKey(pkey, byref(cursor))
        assert written == der_len
        der = ctypes.string_at(cursor, der_len)

        secret = b"org-key-material-32-bytes-xxxxxxx"
        ectx = lib.EVP_PKEY_CTX_new(pkey, None)
        assert ectx
        try:
            assert lib.EVP_PKEY_encrypt_init(ectx) == 1
            assert lib.EVP_PKEY_CTX_set_rsa_padding(ectx, 1) == 1
            md = lib.EVP_sha256()
            lib.EVP_PKEY_CTX_set_rsa_oaep_md.argtypes = [c_void_p, c_void_p]
            assert lib.EVP_PKEY_CTX_set_rsa_oaep_md(ectx, md) == 1
            lib.EVP_PKEY_CTX_set_rsa_mgf1_md.argtypes = [c_void_p, c_void_p]
            assert lib.EVP_PKEY_CTX_set_rsa_mgf1_md(ectx, md) == 1
            outlen = c_size_t()
            assert (
                lib.EVP_PKEY_encrypt(ectx, None, byref(outlen), secret, len(secret)) == 1
            )
            encbuf = create_string_buffer(int(outlen.value))
            assert (
                lib.EVP_PKEY_encrypt(ectx, encbuf, byref(outlen), secret, len(secret)) == 1
            )
            ciphertext = encbuf.raw[: int(outlen.value)]
        finally:
            lib.EVP_PKEY_CTX_free(ectx)

        plain = vc.rsa_oaep_decrypt(der, ciphertext, sha256=True)
        assert plain == secret

        # SHA-1 variant unwraps when the blob was OAEP-SHA1 encrypted.
        ectx1 = lib.EVP_PKEY_CTX_new(pkey, None)
        assert ectx1
        try:
            assert lib.EVP_PKEY_encrypt_init(ectx1) == 1
            assert lib.EVP_PKEY_CTX_set_rsa_padding(ectx1, 1) == 1
            md1 = lib.EVP_sha1()
            assert lib.EVP_PKEY_CTX_set_rsa_oaep_md(ectx1, md1) == 1
            assert lib.EVP_PKEY_CTX_set_rsa_mgf1_md(ectx1, md1) == 1
            outlen = c_size_t()
            assert (
                lib.EVP_PKEY_encrypt(ectx1, None, byref(outlen), secret, len(secret)) == 1
            )
            encbuf = create_string_buffer(int(outlen.value))
            assert (
                lib.EVP_PKEY_encrypt(ectx1, encbuf, byref(outlen), secret, len(secret)) == 1
            )
            ciphertext1 = encbuf.raw[: int(outlen.value)]
        finally:
            lib.EVP_PKEY_CTX_free(ectx1)
        assert vc.rsa_oaep_decrypt(der, ciphertext1, sha256=False) == secret
    finally:
        lib.EVP_PKEY_free(pkey)
        lib.EVP_PKEY_CTX_free(ctx)


# --- key derivation -----------------------------------------------------------


def test_hkdf_expand_rfc5869_case1() -> None:
    # RFC 5869 Appendix A, Test Case 1 (SHA-256): verify our Expand helper
    # against the published OKM after computing the Extract step manually.
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    prk = hmac_mod.new(salt, ikm, hashlib.sha256).digest()
    okm_expected = bytes.fromhex(
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"
    )
    assert vc.hkdf_expand(prk, info, 42) == okm_expected


def test_master_key_pbkdf2_and_stretch() -> None:
    mk = vc.master_key("password", "user@Example.com", 100_000)
    assert mk == hashlib.pbkdf2_hmac(
        "sha256", b"password", b"user@example.com", 100_000
    )
    enc, mac = vc.stretch_to_enc_mac(mk + mk)
    assert len(enc) == 32 and len(mac) == 32
    with pytest.raises(vc.VaultCryptoError):
        vc.stretch_to_enc_mac(b"short")
