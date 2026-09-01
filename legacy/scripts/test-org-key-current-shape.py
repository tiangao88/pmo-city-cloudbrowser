#!/usr/bin/env python3
"""RED/GREEN regression for the current Bitwarden org-key response shape.

The current /api/sync payload carries organization keys at
profile.organizations[].key as CipherString type 4 (RSA-OAEP-SHA1), while the
older payload used keys.organizationKeys[].key encrypted by the user key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))

import vault_client
from pyaes import AESModeOfOperationCBC, Encrypter

# Synthetic RSA-OAEP-SHA1 fixture generated locally; it is not a live secret.
PRIVATE_DER = base64.b64decode(
    "MIICXAIBAAKBgQDa1lcokhh57IicOhE2KukpYCI9/oaMvU6DNe5dx6trbw3BADnefCBX+SWZ6HDsdTJUDnAmh3D70MluXEtDfqcVbEKBn8HlJVjXJqiQEcjSrI6LR04BNVp7aSxPl4DjSBRAKNonp7i8e+1WY+kPwFiO63RaYrcLCKhEOYmz90pk5wIDAQABAoGBAILhhqdBGVpyWRH2uKyI5YJVeKVTQO2Tmw1mh/WWobNTbApuNC4YVs/GtvJhzofdYAhdyj2A69XvfUl/8ZOggBR4r2mGsXKY/1fBpXNVG9IWmB88uH7FieFP6yAnGdHM0ANgDJbLq9SqPNAUKDRA4pZmPT2tugcmLO2GszKgaSWBAkEA9MDjBRYNE8NLTuC4PhzKhrYK3SFChC2JQsefISTS06+s3KMuRBTZDi+BLnCFF/MS/PIJYQm4rmxBoQYnVFIz1wJBAOTkl9mjte7t+Y/Zrh1MUI0GhakPR3Gb4XG8O+4GoRecWe0yq8vB+3n1XBYlHxf1TrrV/ubtRS8gogot9G8qNXECQHVd5b9zopO+i+doRZGrdscAltcRcvc1auP2G+3l3Z+bV5Z6Pd5x7OArkZP2ayxf6NQZMLwy0Df8O8B+1e9OeAMCQCwJsxGDhuBmVsqPZglrAmBvrc2eC+/WvuREA//CtMG3KjIRuq3kL38Cbuov0DCq2K/ntjg11EbB74sn1kyBAXECQAxgrGkAFui+9EQ1vs0SjRPE15y6f4admIHYJfog0X4qiImE1vKZQ3ZrFKJLq5SoHX8wMX5NM6XKLYHw0j4cMLY="
)
WRAPPED = base64.b64decode(
    "tDv8umzN7Nx/WysCToM3JNZD2qVn/hrKy/kq2qtPKfna40d40s1sTAIyE6ttbyi9juJeKZfKeYlmEwv2Xs28E+PVG/RMNNjXAV5ihsuXocp9yfDBpM0Y9ND9845Ak8SD8M1M6twKRG+mfPGJPn/HlH94e+55EjCfgRdGtNQSJes="
)
EXPECTED = b"synthetic-org-key"
USER_KEY = bytes(range(64))


def _enc_bytes(plain, key64):
    iv = b"\x01" * 16
    mode = AESModeOfOperationCBC(key64[:32], iv)
    enc = Encrypter(mode)
    ct = enc.feed(plain) + enc.feed()
    mac = hmac.new(key64[32:], iv + ct, hashlib.sha256).digest()
    b64 = base64.b64encode
    return "2." + b64(iv).decode() + "|" + b64(ct).decode() + "|" + b64(mac).decode()


def test_current_org_key_shape():
    got = vault_client.decrypt_rsa_oaep_sha1_b64(
        "4." + base64.b64encode(WRAPPED).decode(), PRIVATE_DER
    )
    assert got == EXPECTED


def test_current_profile_shape_is_supported():
    sync = {
        "profile": {
            "privateKey": _enc_bytes(PRIVATE_DER, USER_KEY),
            "organizations": [{
                "id": "org-1",
                "key": "4." + base64.b64encode(WRAPPED).decode(),
            }],
        },
        "ciphers": [],
    }
    assert vault_client.organization_keys(sync, USER_KEY) == {"org-1": EXPECTED}


if __name__ == "__main__":
    for fn in (test_current_org_key_shape, test_current_profile_shape_is_supported):
        fn()
        print("PASS", fn.__name__)
