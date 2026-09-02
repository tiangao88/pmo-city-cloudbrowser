"""RED-stage tests for the human MFA handoff (PRD-BR-06 chat-ask path).

- A request to the handoff context returns only an opaque token;
  no code is ever stored, logged, or echoed back.
- A subsequent submit is one-shot per (principal, request_id) and returns only
  a status; the broker never retains or returns the code.
- An unsupported MFA modality returns ``unsupported`` status, never
  ``authenticated`` or ``failed`` masquerading as success.
"""

from __future__ import annotations

from cloudbrowser.credential_broker.adapters.human_handoff import (
    HumanHandoffStore,
    human_handoff_request,
    human_handoff_submit,
)


def test_handoff_issues_opaque_token_for_principal() -> None:
    store = HumanHandoffStore()
    token = human_handoff_request(store, principal_id="alice@example.test", site_id="s-1")
    assert isinstance(token, str) and len(token) >= 16
    assert "alice@example.test" not in token


def test_handoff_submit_consumes_token_once_and_returns_status() -> None:
    store = HumanHandoffStore()
    token = human_handoff_request(store, principal_id="alice@example.test", site_id="s-1")
    status = human_handoff_submit(store, principal_id="alice@example.test", token=token, code="123456")
    assert status == "authenticated"
    second = human_handoff_submit(store, principal_id="alice@example.test", token=token, code="654321")
    assert second == "failed"


def test_handoff_replays_for_wrong_principal() -> None:
    store = HumanHandoffStore()
    token = human_handoff_request(store, principal_id="alice@example.test", site_id="s-1")
    status = human_handoff_submit(store, principal_id="bob@example.test", token=token, code="123456")
    assert status == "failed"


def test_handoff_returns_unsupported_for_explicit_modality() -> None:
    store = HumanHandoffStore()
    status = human_handoff_submit(
        store, principal_id="alice@example.test", modality="push", token="x", code=""
    )
    assert status == "unsupported"


def test_handoff_never_contains_code_in_status_envelope() -> None:
    store = HumanHandoffStore()
    token = human_handoff_request(store, principal_id="p", site_id="s")
    status = human_handoff_submit(store, principal_id="p", token=token, code="999999")
    for forbidden in ("999999",):
        assert forbidden not in status
