"""RED-stage RFC 6238 vectors for the broker TOTP utility."""

from cloudbrowser.credential_broker.adapters.totp import compute_totp


def test_rfc6238_sha1_vectors() -> None:
    secret = b"12345678901234567890"
    expected = {
        59: "287082",
        1_111_111_109: "081804",
        1_111_111_111: "050471",
        1_234_567_890: "005924",
        2_000_000_000: "279037",
        20_000_000_000: "353130",
    }
    for timestamp, code in expected.items():
        assert compute_totp(secret, timestamp, period=30, digits=6) == code
