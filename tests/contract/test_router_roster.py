"""Roster contract: who is waiting and who holds the slot.

The roster exposes each live session's status and its non-authoritative
display email captured from the edge at join time. The email is display
metadata only — identity itself is still resolved exclusively through the
identity-link service, and principal IDs, bindings, and slot URLs are
never part of any roster payload.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from typing import Mapping

import pytest

from cloudbrowser.router.router_api import RouterApi
from cloudbrowser.router.sessions import RouterSessionStore, SlotDescriptor


def _slots() -> tuple[SlotDescriptor, ...]:
    return (
        SlotDescriptor("slot-1", "http://sup-1", "browser-slot-1"),
        SlotDescriptor("slot-2", "http://sup-2", "browser-slot-2"),
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Identity:
    """Resolve each edge identity to a distinct principal, or None when absent."""

    def __init__(self, principal: str | None = "pmo-a") -> None:
        self._principal = principal

    def resolve(self, identity: object) -> str | None:
        if self._principal is None:
            return None
        sub = getattr(identity, "sub", None)
        if sub == "sub-2":
            return "pmo-b"
        return self._principal


class _Supervisor:
    known_slots = frozenset({"slot-1", "slot-2"})

    def post_control(self, slot_id: str, *, operation: str, request_id: str) -> dict[str, object]:
        return {"status": "ready", "state": "ready", "restored_count": 0}


_HEADERS = {"Remote-Sub": "sub-1", "Remote-Email": "a@example.com"}


def _api(tmp_path, principal: str | None = "pmo-a") -> RouterApi:
    store = RouterSessionStore(tmp_path / "router.json", slots=_slots(), clock=_Clock())
    return RouterApi(
        session_store=store,
        supervisor_client=_Supervisor(),
        identity_client=_Identity(principal),  # type: ignore[arg-type]
    )


def _post(api: RouterApi, email: str | None = None) -> tuple[int, dict[str, object]]:
    headers = dict(_HEADERS)
    if email is None:
        headers.pop("Remote-Email")
    else:
        headers["Remote-Email"] = email
    return api.open_session(headers=headers, body={"request_id": "r1"})


class TestStoreDisplayEmail:
    def test_enqueue_captures_display_email_from_header(self, tmp_path) -> None:
        store = RouterSessionStore(tmp_path / "s.json", slots=_slots(), clock=_Clock())
        store.enqueue("pmo-a", request_id="r1", display_email="a@example.com")
        record = store.for_principal("pmo-a")
        assert record is not None
        assert record.display_email == "a@example.com"

    def test_enqueue_without_email_stays_absent(self, tmp_path) -> None:
        store = RouterSessionStore(tmp_path / "s.json", slots=_slots(), clock=_Clock())
        store.enqueue("pmo-a", request_id="r1")
        record = store.for_principal("pmo-a")
        assert record is not None
        assert record.display_email is None

    def test_display_email_survives_restart(self, tmp_path) -> None:
        path = tmp_path / "s.json"
        store = RouterSessionStore(path, slots=_slots(), clock=_Clock())
        store.enqueue("pmo-a", request_id="r1", display_email="a@example.com")
        restored = RouterSessionStore(path, slots=_slots(), clock=_Clock())
        record = restored.for_principal("pmo-a")
        assert record is not None
        assert record.display_email == "a@example.com"

    def test_state_file_never_gains_email_key_when_absent(self, tmp_path) -> None:
        path = tmp_path / "s.json"
        store = RouterSessionStore(path, slots=_slots(), clock=_Clock())
        store.enqueue("pmo-a", request_id="r1")
        assert "display_email" not in json.loads(path.read_text())["sessions"][0]

    @pytest.mark.parametrize("bad", ["x" * 257, "bad@value\n", 123])
    def test_invalid_display_email_is_rejected(self, tmp_path, bad) -> None:
        store = RouterSessionStore(tmp_path / "s.json", slots=_slots(), clock=_Clock())
        with pytest.raises(ValueError):
            store.enqueue("pmo-a", request_id="r1", display_email=bad)

    def test_public_dict_never_contains_the_email(self, tmp_path) -> None:
        store = RouterSessionStore(tmp_path / "s.json", slots=_slots(), clock=_Clock())
        session = store.enqueue("pmo-a", request_id="r1", display_email="a@example.com")
        assert "display_email" not in session.public_dict()


class TestRosterEndpoint:
    def test_roster_lists_waiting_and_active_with_emails(self, tmp_path) -> None:
        api = _api(tmp_path)
        _post(api, email="a@example.com")  # pmo-a waiting (email from header)
        api.open_session(
            headers={"Remote-Sub": "sub-2", "Remote-Email": "b@example.com"},
            body={"request_id": "r2"},
        )  # pmo-b promoted to offered
        status, payload = api.roster(headers=dict(_HEADERS))
        assert status == 200
        entries = payload["entries"]
        assert [entry["email"] for entry in entries] == ["a@example.com", "b@example.com"]
        assert [entry["status"] for entry in entries] == ["offered", "offered"]

    def test_roster_excludes_left_and_stopped_sessions(self, tmp_path) -> None:
        api = _api(tmp_path)
        _post(api, email="a@example.com")
        api.leave_session(headers=dict(_HEADERS), request_id="r9")
        status, payload = api.roster(headers=dict(_HEADERS))
        assert status == 200
        assert payload["entries"] == []

    def test_roster_without_resolvable_identity_fails_closed(self, tmp_path) -> None:
        api = _api(tmp_path, principal=None)
        status, payload = api.roster(headers={"Remote-Sub": "forged"})
        assert status == 401
        assert payload["error_code"] == "unauthorized"

    def test_roster_entry_without_email_has_no_email_key(self, tmp_path) -> None:
        api = _api(tmp_path)
        _post(api, email=None)
        _, payload = api.roster(headers=dict(_HEADERS))
        assert "email" not in payload["entries"][0]


class TestRosterHttpDispatch:
    def _server(self, tmp_path):
        from cloudbrowser.router.router_api import create_router_server

        api = _api(tmp_path)
        server = create_router_server(api, address=("127.0.0.1", 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://{server.server_address[0]}:{server.server_address[1]}"

    def test_get_v1_roster_returns_entries(self, tmp_path) -> None:
        from urllib.request import Request, urlopen

        server, thread, base = self._server(tmp_path)
        try:
            # enqueue through the HTTP layer itself
            req = Request(
                base + "/v1/session",
                data=json.dumps({"request_id": "r1"}).encode(),
                headers={"Content-Type": "application/json", **{k: v for k, v in _HEADERS.items()}},
                method="POST",
            )
            urlopen(req).read()
            get = Request(base + "/v1/roster", headers=dict(_HEADERS), method="GET")
            with urlopen(get) as response:
                payload = json.loads(response.read())
            assert payload["entries"][0]["email"] == "a@example.com"
            assert payload["entries"][0]["status"] in {"waiting", "offered"}
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()
