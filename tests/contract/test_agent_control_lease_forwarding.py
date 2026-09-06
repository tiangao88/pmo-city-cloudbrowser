"""RED tests: transparent agent-control lease rotation before forwarding.

The router mints per-session bindings (``generation-{session_id}``); the
agent-control service starts with a statically pinned binding and only
accepts forwarded page actions once its trusted lease is rotated via
``POST /agent-control/lease``. The forwarder must therefore, on a 401
(stale lease), rotate the lease with the server-derived session binding
and retry the forwarded action exactly once — still failing closed when
the rotation is refused.
"""

from __future__ import annotations

import json

import pytest

from cloudbrowser.browser_slots import BrowserBinding
from cloudbrowser.router.agent_control_forwarder import (
    AgentControlForwarder,
    AgentControlUnavailable,
)


_SECRET = "router-agent-shared-secret-0123456789"

_BINDING = BrowserBinding(
    principal_id="pmo-owner",
    profile_id="profile-pmo-owner",
    browser_id="browser-slot-1",
    generation="generation-q-abc123",
)


class _FakeRequester:
    """Records requests; scripted (status, body) responses per path."""

    def __init__(self, responses: list[tuple[str, int, dict[str, object]]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def _record(self, path: str, body: dict[str, object], headers: dict[str, str]) -> None:
        self.calls.append((path, body, dict(headers)))

    def _next(self, path: str) -> tuple[int, bytes]:
        for index, (want, status, payload) in enumerate(self._responses):
            if want == path:
                del self._responses[index]
                return status, json.dumps(payload).encode("utf-8")
        raise AssertionError(f"unexpected request to {path}")

    def post(
        self,
        body: dict[str, object],
        *,
        principal_id: str,
        browser_id: str,
        generation: str,
    ) -> tuple[int, bytes]:
        headers = {
            "X-CB-Trusted-Secret": _SECRET,
            "X-CB-Principal": principal_id,
            "X-CB-Browser": browser_id,
            "X-CB-Generation": generation,
        }
        self._record("/agent-control/v1", dict(body), headers)
        return self._next("/agent-control/v1")

    def post_lease(self, body: dict[str, object]) -> tuple[int, bytes]:
        headers = {"X-CB-Trusted-Secret": _SECRET}
        self._record("/agent-control/lease", dict(body), headers)
        return self._next("/agent-control/lease")


def _forwarder(requester: _FakeRequester) -> AgentControlForwarder:
    return AgentControlForwarder(
        {"slot-1": "http://agent-control:8090"},
        trusted_secret=_SECRET,
        requester_factory=lambda base_url, timeout_s: requester,
    )


def test_forward_rotates_stale_lease_then_retries_action() -> None:
    requester = _FakeRequester(
        [
            ("/agent-control/v1", 401, {"status": "failed", "error_code": "unauthorized"}),
            ("/agent-control/lease", 200, {"status": "ok"}),
            (
                "/agent-control/v1",
                200,
                {"request_id": "req-1", "status": "ok", "page": {"url": "https://example.test"}},
            ),
        ]
    )
    forwarder = _forwarder(requester)
    result = forwarder.forward(
        "slot-1",
        binding=_BINDING,
        operation="page_info",
        params={},
        request_id="req-1",
    )
    assert result["status"] == "ok"
    paths = [path for path, _body, _headers in requester.calls]
    assert paths == ["/agent-control/v1", "/agent-control/lease", "/agent-control/v1"]
    lease_path, lease_body, lease_headers = requester.calls[1]
    assert lease_body == {
        "binding": {
            "principal_id": _BINDING.principal_id,
            "profile_id": _BINDING.profile_id,
            "browser_id": _BINDING.browser_id,
            "generation": _BINDING.generation,
        }
    }
    assert lease_headers["X-CB-Trusted-Secret"] == _SECRET
    # The retry carries the session binding envelope, not caller input.
    _path, _body, retry_headers = requester.calls[2]
    assert retry_headers["X-CB-Generation"] == _BINDING.generation


def test_forward_does_not_rotate_lease_when_first_attempt_succeeds() -> None:
    requester = _FakeRequester(
        [
            ("/agent-control/v1", 200, {"request_id": "req-1", "status": "ok"}),
        ]
    )
    forwarder = _forwarder(requester)
    forwarder.forward(
        "slot-1",
        binding=_BINDING,
        operation="page_info",
        params={},
        request_id="req-1",
    )
    assert [path for path, _b, _h in requester.calls] == ["/agent-control/v1"]


def test_forward_fails_closed_when_lease_rotation_is_refused() -> None:
    requester = _FakeRequester(
        [
            ("/agent-control/v1", 401, {"status": "failed", "error_code": "unauthorized"}),
            ("/agent-control/lease", 401, {"status": "failed", "error_code": "unauthorized"}),
        ]
    )
    forwarder = _forwarder(requester)
    with pytest.raises(AgentControlUnavailable):
        forwarder.forward(
            "slot-1",
            binding=_BINDING,
            operation="page_info",
            params={},
            request_id="req-1",
        )
    assert [path for path, _b, _h in requester.calls] == [
        "/agent-control/v1",
        "/agent-control/lease",
    ]


def test_forward_fails_closed_when_retry_after_rotation_still_unauthorized() -> None:
    requester = _FakeRequester(
        [
            ("/agent-control/v1", 401, {"status": "failed", "error_code": "unauthorized"}),
            ("/agent-control/lease", 200, {"status": "ok"}),
            ("/agent-control/v1", 401, {"status": "failed", "error_code": "unauthorized"}),
        ]
    )
    forwarder = _forwarder(requester)
    with pytest.raises(AgentControlUnavailable):
        forwarder.forward(
            "slot-1",
            binding=_BINDING,
            operation="page_info",
            params={},
            request_id="req-1",
        )
    # Exactly one rotation attempt: no retry loops against a refusing target.
    assert [path for path, _b, _h in requester.calls] == [
        "/agent-control/v1",
        "/agent-control/lease",
        "/agent-control/v1",
    ]
