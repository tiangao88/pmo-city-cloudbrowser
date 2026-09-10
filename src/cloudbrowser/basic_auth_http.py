"""HTTP Basic capability contract over the internal browser sidecar.

This is the only credential-bearing browser channel exposed to the broker.
It is deliberately separate from the normal agent operations:

- ``challenge_origin`` / ``has_basic_auth_challenge`` never reveal headers;
- ``submit_basic_auth`` sends credentials only to the internal browser API;
- ``application_authenticated`` is a boolean proof only;
- no cookies, network bodies, authorization headers, raw CDP, or page content
  cross back to the broker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from cloudbrowser.credential_broker.deadline import accepts_keyword

if TYPE_CHECKING:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline
    from cloudbrowser.credential_broker.runtime import LiveBrowserBinding

from .browser_slots.transport import BrowserUnavailable


class BasicAuthClient(Protocol):
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
class HttpBasicAuthBrowser:
    """Adapt the secret-gated internal browser API to ``BasicAuthBrowser``."""

    client: BasicAuthClient
    shared_secret: str
    deadline: "BrokerDeadline | None" = None
    _last_state: dict[str, str | bool | None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.shared_secret, str) or len(self.shared_secret) < 16:
            raise ValueError("Basic Auth browser secret must be at least 16 characters")

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        timeout_s = self.deadline.check() if self.deadline is not None else None
        if self.deadline is not None:
            headers = dict(headers or {})
            headers.update(self._headers())
        if timeout_s is not None and accepts_keyword(self.client.request, "timeout_s"):
            return self.client.request(
                method,
                path,
                body=body,
                headers=headers,
                timeout_s=timeout_s,
            )
        return self.client.request(method, path, body=body, headers=headers)

    def live_binding(self) -> "LiveBrowserBinding":
        from cloudbrowser.credential_broker.runtime import LiveBrowserBinding

        raw = self._request("GET", "/agent/readiness")
        if not isinstance(raw, dict):
            raise BrowserUnavailable("invalid Basic Auth browser readiness")
        owner = raw.get("owner")
        generation = raw.get("generation")
        cdp_ok = raw.get("cdp_ok")
        profile_id = raw.get("profile_id", "profile-unassigned")
        browser_id = raw.get("browser_id", "browser-unassigned")
        if (
            not isinstance(owner, str)
            or not owner
            or not isinstance(generation, str)
            or not generation
            or not isinstance(profile_id, str)
            or not isinstance(browser_id, str)
            or cdp_ok is not True
        ):
            raise BrowserUnavailable("Basic Auth browser is not ready")
        return LiveBrowserBinding(
            profile_id=profile_id,
            principal_id=owner,
            browser_id=browser_id,
            generation=generation,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"X-CB-Broker-Secret": self.shared_secret}
        if self.deadline is not None:
            headers["X-CB-Broker-Deadline-S"] = f"{self.deadline.check():.6f}"
        return headers

    def _read_state(self, *, target_id: str) -> dict[str, str | bool | None]:
        _validate_target_id(target_id)
        raw = self._request(
            "POST",
            "/broker/basic/state",
            body=_json_body({"target_id": target_id}),
            headers={"Content-Type": "application/json", **self._headers()},
        )
        self._last_state = _state(raw)
        return self._last_state

    def current_url(self, *, target_id: str) -> str:
        value = self._read_state(target_id=target_id)["url"]
        assert isinstance(value, str)
        return value

    def challenge_origin(self, *, target_id: str) -> str | None:
        state = self._read_state(target_id=target_id)
        value = state.get("challenge_origin")
        if value is None:
            return None
        if not isinstance(value, str) or _https_origin(value) != value:
            raise BrowserUnavailable("invalid Basic challenge origin")
        return value

    def has_basic_auth_challenge(self, origin: str, *, target_id: str) -> bool:
        return self.challenge_origin(target_id=target_id) == origin

    def submit_basic_auth(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
    ) -> None:
        if _https_origin(origin) != origin:
            raise ValueError("Basic Auth origin must be an exact HTTPS origin")
        for value, label, maximum in (
            (username, "username", 512),
            (password, "password", 4096),
        ):
            if not isinstance(value, str) or not value or len(value) > maximum:
                raise ValueError(f"Basic Auth {label} is invalid")
            if "\r" in value or "\n" in value or "\x00" in value:
                raise ValueError(f"Basic Auth {label} contains forbidden characters")
        payload = {
            "origin": origin,
            "username": username,
            "password": password,
            "target_id": target_id,
            "success_path": success_path,
        }
        raw = self._request(
            "POST",
            "/broker/basic/submit",
            body=_json_body(payload),
            headers={"Content-Type": "application/json", **self._headers()},
        )
        if not isinstance(raw, dict) or raw.get("ok") is not True:
            raise BrowserUnavailable("Basic Auth submission was not acknowledged")
        self._last_state = None

    def application_authenticated(self, *, target_id: str) -> bool:
        value = self._read_state(target_id=target_id)["application_authenticated"]
        assert isinstance(value, bool)
        return value


def _json_body(payload: dict[str, str]) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"))


def _validate_target_id(target_id: str) -> None:
    if (
        not isinstance(target_id, str)
        or not target_id
        or len(target_id) > 256
        or any(char in target_id for char in ("\r", "\n", "\x00"))
    ):
        raise ValueError("Basic Auth target_id is invalid")


def _state(raw: object) -> dict[str, str | bool | None]:
    if not isinstance(raw, dict):
        raise BrowserUnavailable("invalid Basic Auth state")
    url = raw.get("url")
    challenge = raw.get("challenge_origin")
    authenticated = raw.get("application_authenticated")
    if not isinstance(url, str) or not url or not isinstance(authenticated, bool):
        raise BrowserUnavailable("invalid Basic Auth state")
    if challenge is not None and not isinstance(challenge, str):
        raise BrowserUnavailable("invalid Basic Auth state")
    url = _redact_url(url)
    challenge = _redact_origin(challenge) if challenge is not None else None
    return {
        "url": url,
        "challenge_origin": challenge,
        "application_authenticated": authenticated,
    }


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        raise BrowserUnavailable("invalid Basic Auth state URL")
    return parsed._replace(query="", fragment="").geturl()


def _redact_origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise BrowserUnavailable("invalid Basic Auth challenge origin")
    return f"https://{parsed.netloc}"


def _https_origin(url: str) -> str | None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"https://{parsed.netloc}"


__all__ = ["HttpBasicAuthBrowser"]
