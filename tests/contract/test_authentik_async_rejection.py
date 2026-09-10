"""Post-submit Authentik rejection contracts."""

from __future__ import annotations

from typing import cast

import pytest

from cloudbrowser.browser_slots.authentik import AuthentikActions, AuthentikCapability


class _AsyncRejectingActions:
    def __init__(self) -> None:
        self.rejection_checks = 0

    def broker_authentik_identification(self, target_id: str, **kwargs):
        assert target_id == "target-1"
        assert kwargs["username"] == "alice"
        assert kwargs["password"] == "secret-pw"
        return {
            "stage": "submitted",
            "url": "https://auth.example.test/if/flow/login/",
        }

    def broker_authentik_rejection(self, target_id: str, **kwargs):
        assert target_id == "target-1"
        assert kwargs["expected_origins"] == ("https://auth.example.test",)
        self.rejection_checks += 1
        return {"state": "rejected" if self.rejection_checks >= 2 else "clear"}

    def broker_page_info(self, target_id: str, selector=None):
        assert target_id == "target-1"
        if selector is None:
            return {
                "url": "https://auth.example.test/if/flow/login/?query=private#fragment",
                "title": "",
                "text": "",
            }
        if selector.endswith("validate"):
            return {"found": False, "text": "", "value": ""}
        return {"found": True, "text": "", "value": ""}

    def broker_authentik_proof(self, target_id: str, **kwargs):
        raise AssertionError((target_id, kwargs))

    def broker_navigate(self, target_id: str, url: str):
        raise AssertionError((target_id, url))

    def broker_click(self, target_id: str, selector: str):
        raise AssertionError((target_id, selector))

    def broker_type_text(self, target_id: str, selector: str, text: str):
        raise AssertionError((target_id, selector, text))


def test_authentik_stage_timeout_cannot_outlive_router_deadline() -> None:
    with pytest.raises(ValueError, match="stage timeout"):
        AuthentikCapability(
            cast(AuthentikActions, _AsyncRejectingActions()),
            ("https://auth.example.test",),
            (),
            (),
            stage_timeout_s=30.1,
        )


def test_post_submit_explicit_rejection_is_reported_without_dom_or_url_secrets() -> None:
    actions = _AsyncRejectingActions()
    capability = AuthentikCapability(
        cast(AuthentikActions, actions),
        ("https://auth.example.test",),
        (),
        (),
        stage_timeout_s=0.2,
        poll_interval_s=0.001,
    )

    result = capability.identification(
        target_id="target-1", username="alice", password="secret-pw"
    )

    assert result == {"outcome": "rejected"}
    assert actions.rejection_checks == 2
    serialized = repr(result)
    assert "query" not in serialized
    assert "fragment" not in serialized
    assert "role=alert" not in serialized
