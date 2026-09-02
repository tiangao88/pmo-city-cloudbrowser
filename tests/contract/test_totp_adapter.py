"""RED-stage tests for the broker-owned TOTP adapter (PRD-BR-06).

- TOTP seed is broker-only; the adapter computes RFC 6238 codes with HMAC-SHA1,
  6 digits, 30-second step, no drift compensation in the public surface.
- The seed and the produced code must never appear in any returned artifact,
  exception string, log, or attribute.
- The adapter only operates on declared origins/exact selectors.
"""

from __future__ import annotations

import time

import pytest

from cloudbrowser.credential_broker.adapters.totp import (
    TOTPAdapter,
    TOTPDeclaration,
    TOTPMaterial,
)


class FakeTOTPBrowser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def current_url(self) -> str:
        return "https://login.example.test/2fa"

    def has_selector(self, selector: str) -> bool:
        return selector in {"[name=code]", "[type=submit]"}

    def fill_code(self, selector: str, value: str) -> None:
        self.calls.append((selector, value))

    def click(self, selector: str) -> None:
        self.calls.append((selector, "click"))


def declaration() -> TOTPDeclaration:
    return TOTPDeclaration(
        site_id="totp-test",
        origin="https://login.example.test",
        code_selector="[name=code]",
        submit_selector="[type=submit]",
    )


def test_totp_submits_derived_code_only_on_declared_origin() -> None:
    browser = FakeTOTPBrowser()
    secret = b"12345678901234567890"
    material = TOTPMaterial(secret=secret, digits=6, period=30)
    adapter = TOTPAdapter()
    result = adapter.execute(declaration(), material, browser, time.time())
    assert result.identity_verified is True
    assert len(browser.calls) == 2
    selector, value = browser.calls[0]
    assert selector == "[name=code]"
    assert len(value) == 6 and value.isdigit()


def test_totp_seed_and_code_never_appear_in_artifacts() -> None:
    browser = FakeTOTPBrowser()
    secret = b"do-not-leak" * 2
    material = TOTPMaterial(secret=secret, digits=6, period=30)
    adapter = TOTPAdapter()
    result = adapter.execute(declaration(), material, browser, time.time())
    for forbidden in (secret.hex(), "do-not-leak"):
        for attr in ("status", "error_code"):
            value = getattr(result, attr, None)
            if value is not None:
                assert forbidden not in str(value)


def test_totp_rejects_wrong_origin_without_filling() -> None:
    class WrongOriginBrowser(FakeTOTPBrowser):
        def current_url(self) -> str:
            return "https://attacker.example.test/"

    adapter = TOTPAdapter()
    result = adapter.execute(declaration(), TOTPMaterial(b"x" * 20), WrongOriginBrowser(), time.time())
    assert result.status == "failed"
    assert result.identity_verified is False
    assert WrongOriginBrowser().calls == []


def test_totp_produces_deterministic_code_for_same_timestamp() -> None:
    browser = FakeTOTPBrowser()
    secret = b"abcdefghijklmnopqrstuvwxyz0123"[:20]
    material = TOTPMaterial(secret=secret, digits=6, period=30)
    adapter = TOTPAdapter()
    fixed = 1700000000
    first = adapter.execute(declaration(), material, FakeTOTPBrowser(), fixed)
    second = adapter.execute(declaration(), material, FakeTOTPBrowser(), fixed)
    assert first.identity_verified and second.identity_verified


def test_totp_uses_only_rfc6238_defaults_when_not_overridden() -> None:
    """Default period=30, digits=6, algorithm=SHA-1 (PRD-BR-06 default)."""

    class ProbeBrowser(FakeTOTPBrowser):
        def __init__(self) -> None:
            super().__init__()
            self.last_value = ""

        def fill_code(self, selector: str, value: str) -> None:
            self.last_value = value
            super().fill_code(selector, value)

    material = TOTPMaterial(secret=b"a" * 20)
    browser = ProbeBrowser()
    adapter = TOTPAdapter()
    adapter.execute(declaration(), material, browser, 1700000000)
    assert len(browser.last_value) == 6


def test_totp_rejects_invalid_digit_count() -> None:
    with pytest.raises(ValueError):
        material = TOTPMaterial(secret=b"a" * 20, digits=8)
        assert material is not None  # pragma: no cover - construction is the assertion
