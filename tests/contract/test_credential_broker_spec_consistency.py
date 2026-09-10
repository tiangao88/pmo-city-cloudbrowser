"""Keep credential-broker status prose aligned with the secure runtime gate."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_form_mode_status_matches_startup_guard_and_skipped_e2e() -> None:
    runtime = _read("src/cloudbrowser/credential_broker/runtime.py")
    layer4 = _read("tests/integration/test_broker_layer4_adapter.py")
    durable_plan = _read("specs/proposals/v0.2/durable-plan.md")
    readme = _read("services/credential-broker/README.md")

    assert "CB_BROKER_ADAPTER=form is disabled" in runtime
    assert "pytestmark = pytest.mark.skip" in layer4
    assert "production form mode is disabled" in layer4
    assert len(re.findall(r"^def test_", layer4, flags=re.MULTILINE)) == 3
    status_docs = "\n".join(
        (
            durable_plan,
            readme,
            _read("specs/proposals/v0.2/95-w3-1-broker-login-e2e.md"),
            _read("specs/proposals/v0.2/roadmap-w3-status.md"),
        )
    )
    status_text = status_docs.lower()
    for text in (
        "form proof is historical only",
        "form login",
        "unavailable",
        "not qualified",
    ):
        assert text in status_text
    assert "CB_BROKER_GRANT_USERNAME_REF" not in readme
    for durable_boundary in (
        "principal-scoped durable grant",
        "idempotency",
        "nonce",
    ):
        assert durable_boundary in readme.lower()
    assert re.search(r"opaque,\s*signed, one-time capability", readme)
    for stale_claim in (
        "layers 1-4 shipped (form adapter)",
        "form and http basic adapters are wired locally",
        "w3-1 → pass",
    ):
        assert stale_claim not in status_text


def test_mfa_status_does_not_turn_detection_into_submission_or_handoff() -> None:
    status_docs = "\n".join(
        _read(path)
        for path in (
            "specs/proposals/v0.2/durable-plan.md",
            "specs/proposals/v0.2/95-w3-1-broker-login-e2e.md",
            "specs/proposals/v0.2/roadmap-w3-status.md",
            "services/credential-broker/README.md",
        )
    ).lower()

    for text in (
        "totp submission",
        "human one-time-code handoff",
        "live authentik closed-shadow qualification",
        "not qualified",
    ):
        assert text in status_docs
    assert "detects the authentik mfa stage" in status_docs
    assert "no totp submission" in status_docs
    assert "no human one-time-code handoff" in status_docs


def test_prd_keeps_form_totp_and_handoff_as_final_product_requirements() -> None:
    prd = _read("specs/proposals/v0.2/85-credential-broker-prd.md")

    for requirement in (
        "ordinary username/password form",
        "TOTP at an application or IdP MFA stage",
        "human one-time-code handoff",
        "stored TOTP seed → broker computes and submits the code",
        "no stored seed → one-time human code request",
    ):
        assert requirement in prd
    assert "current pre-login" in prd.lower()


def test_release_docs_preserve_the_post_commit_pin_sequence() -> None:
    release_docs = "\n".join(
        _read(path)
        for path in (
            "specs/proposals/v0.2/durable-plan.md",
            "specs/proposals/v0.2/89-image-publication-and-qualification.md",
            "deploy/coolify/releases/README.md",
        )
    ).lower()

    for step in (
        "source commit",
        "user/operator trigger",
        "digest/provenance sync",
        "stale image pins",
        "do not edit them now",
    ):
        assert step in release_docs
    assert "stale pins" in release_docs
    assert "release sequence" in release_docs
