"""Broker-only bounded Authentik capability client."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from cloudbrowser.credential_broker.deadline import accepts_keyword

if TYPE_CHECKING:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline

from .browser_slots.transport import BrowserUnavailable

_MAX_STAGE_TIMEOUT_S = 30.0
_MAX_HTTP_TIMEOUT_S = 30.0
_HTTP_OVERHEAD_S = 0.5


def _validate_target_id(target_id: str) -> None:
    if (
        not isinstance(target_id, str)
        or not target_id
        or len(target_id.encode("utf-8")) > 256
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in target_id)
    ):
        raise ValueError("Authentik target_id is invalid")


def _validate_text(value: str, label: str, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"Authentik {label} is invalid")


class AuthentikClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> object: ...


@dataclass
class HttpAuthentikBrowser:
    """Expose only fixed Authentik operations required by the SSO adapter."""

    client: AuthentikClient
    shared_secret: str
    target_id: str
    stage_timeout_s: float | None = None
    deadline: "BrokerDeadline | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.shared_secret, str) or len(self.shared_secret) < 16:
            raise ValueError("Authentik browser secret must be at least 16 characters")
        _validate_target_id(self.target_id)
        if self.stage_timeout_s is None:
            try:
                self.stage_timeout_s = float(
                    os.environ.get("CB_BROKER_SSO_STAGE_TIMEOUT_S", "30")
                )
            except ValueError as exc:
                raise ValueError("Authentik stage timeout is invalid") from exc
        if isinstance(self.stage_timeout_s, bool) or not isinstance(
            self.stage_timeout_s, (int, float)
        ) or not 0 < self.stage_timeout_s <= _MAX_STAGE_TIMEOUT_S:
            raise ValueError("Authentik stage timeout is invalid")
        client_timeout = getattr(self.client, "_timeout_s", None)
        # This transport covers only the browser stage. Keep a small allowance
        # for HTTP framing while the router owns the single end-to-end deadline.
        required_timeout = min(
            _MAX_HTTP_TIMEOUT_S, float(self.stage_timeout_s) + _HTTP_OVERHEAD_S
        )
        if isinstance(client_timeout, (int, float)):
            try:
                setattr(self.client, "_timeout_s", required_timeout)
            except (AttributeError, TypeError) as exc:
                raise ValueError("Authentik HTTP deadline cannot be aligned") from exc

    def _post(
        self,
        path: str,
        *,
        deadline: "BrokerDeadline | None" = None,
        **fields: str,
    ) -> dict[str, object]:
        import json

        effective_deadline = deadline if deadline is not None else self.deadline

        if path not in {
            "/broker/authentik/state",
            "/broker/authentik/begin",
            "/broker/authentik/identification",
            "/broker/authentik/proof",
        }:
            raise ValueError("unsupported Authentik capability operation")
        _validate_target_id(self.target_id)
        timeout_s = effective_deadline.check() if effective_deadline is not None else None
        body = json.dumps({"target_id": self.target_id, **fields})
        headers = {"X-CB-Broker-Secret": self.shared_secret}
        if effective_deadline is not None:
            headers["X-CB-Broker-Deadline-S"] = f"{effective_deadline.check():.6f}"
        if timeout_s is not None and accepts_keyword(self.client.request, "timeout_s"):
            raw = self.client.request(
                "POST",
                path,
                body=body,
                headers=headers,
                timeout_s=timeout_s,
            )
        else:
            raw = self.client.request("POST", path, body=body, headers=headers)
        if not isinstance(raw, dict):
            raise BrowserUnavailable("invalid Authentik capability response")
        return raw

    def current_url(self, *, deadline: "BrokerDeadline | None" = None) -> str:
        value = self._post("/broker/authentik/state", deadline=deadline).get("url")
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 2048:
            raise BrowserUnavailable("invalid Authentik state")
        return value

    def begin_authentik(
        self,
        entry_url: str,
        *,
        deadline: "BrokerDeadline | None" = None,
    ) -> None:
        if not isinstance(entry_url, str) or not entry_url or len(entry_url.encode("utf-8")) > 2048:
            raise ValueError("Authentik entry URL is invalid")
        self._post("/broker/authentik/begin", deadline=deadline, entry_url=entry_url)

    def identification(
        self,
        username: str,
        password: str,
        *,
        deadline: "BrokerDeadline | None" = None,
    ) -> str:
        _validate_text(username, "username", 512)
        _validate_text(password, "password", 4096)
        value = self._post(
            "/broker/authentik/identification",
            deadline=deadline,
            username=username,
            password=password,
        ).get("outcome")
        if value not in {"submitted", "accepted", "rejected", "denied"}:
            raise BrowserUnavailable("invalid Authentik identification state")
        return str(value)

    def mfa_stage(self, *, deadline: "BrokerDeadline | None" = None) -> str | None:
        value = self._post("/broker/authentik/state", deadline=deadline).get("modality")
        return value if isinstance(value, str) and value else None

    def application_identity(self, *, deadline: "BrokerDeadline | None" = None) -> str | None:
        value = self._post("/broker/authentik/proof", deadline=deadline).get("account")
        return value if isinstance(value, str) and value else None

    @property
    def timeout_s(self) -> float:
        assert self.stage_timeout_s is not None
        return float(self.stage_timeout_s)


__all__ = ["AuthentikClient", "HttpAuthentikBrowser"]
