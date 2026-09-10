"""Secret-gated broker-only HTTP Basic capability for local Chrome.

The capability is intentionally separate from ``PageActionAdapter`` and is
never reachable from router/agent-control. It uses one short-lived local CDP
connection per probe or submission:

* ``probe`` enables Fetch auth events, reloads the current page, cancels a
  matching Basic challenge, and returns only its origin;
* ``submit`` repeats the reload and answers exactly one matching challenge;
* a second matching challenge is retained as metadata so ``BasicAuthAdapter``
  returns ``challenge_loop`` rather than claiming success;
* state contains only URL/origin/boolean proof — never headers or values.

The browser service exposes this object only behind its broker shared-secret
HTTP endpoints. Credentials exist in memory only for the submit call and in
the single CDP ``Fetch.continueWithAuth`` command.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline

from .transport import BrowserUnavailable


class BasicAuthCapability:
    """One-origin, one-challenge Basic Auth capability over local CDP."""

    def __init__(
        self,
        chrome: Any,
        *,
        ws_factory: Callable[[str, float], Any],
        timeout_s: float = 5.0,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._chrome = chrome
        self._ws_factory = ws_factory
        self._timeout_s = timeout_s
        self._state = BasicAuthState("", "", None, False)
        self._lock = threading.Lock()

    def state(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | bool | None]:
        """Return public state with URL credentials stripped to origin/path."""
        _check_deadline(deadline)
        url = _redact_url(self._target_url_or_last(target_id, deadline=deadline))
        challenge_origin = (
            self._state.challenge_origin if self._state.target_id == target_id else None
        )
        authenticated = bool(
            self._state.target_id == target_id
            and self._state.application_authenticated
            and _origin(url) == _origin(self._state.url)
        )
        return {
            "url": url,
            "challenge_origin": challenge_origin,
            "application_authenticated": authenticated,
        }

    def probe(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | bool | None]:
        """Detect and cancel a Basic challenge on one exact target."""
        if not self._lock.acquire(blocking=False):
            raise BrowserUnavailable("Basic Auth capability is busy")
        try:
            self._probe(
                target_id=target_id,
                current_url=self._current_url(target_id=target_id, deadline=deadline),
                deadline=deadline,
            )
            return self.state(target_id=target_id, deadline=deadline)
        finally:
            self._lock.release()

    def observe_challenge(self, origin: str, *, target_id: str = "target-1") -> None:
        """Record a challenge for an in-process test or controlled harness."""
        if _origin(origin) != origin:
            raise ValueError("challenge origin must be an exact HTTPS origin")
        self._state = BasicAuthState(
            target_id,
            self._current_url(target_id=target_id),
            origin,
            False,
        )

    def submit(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> None:
        """Answer one declared-origin challenge on one exact target."""
        if not self._lock.acquire(blocking=False):
            raise BrowserUnavailable("Basic Auth capability is busy")
        try:
            self._submit(
                origin,
                username,
                password,
                target_id=target_id,
                success_path=success_path,
                deadline=deadline,
            )
        finally:
            self._lock.release()

    def _submit(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> None:
        _validate_credential(origin, username, password)
        _validate_target_id(target_id)
        _validate_success_path(success_path)
        _check_deadline(deadline)
        current = self._target_url_or_last(target_id, deadline=deadline)
        if _origin(current) != origin:
            raise ValueError("current page is not the declared Basic Auth origin")
        timeout_s = min(
            self._timeout_s,
            deadline.check() if deadline is not None else self._timeout_s,
        )
        ws = self._ws_factory(self._page_websocket(target_id, deadline=deadline), timeout_s)
        challenge_seen = False
        credentials_sent = False
        challenge_loop = False
        try:
            self._enable_interception(ws, origin)
            self._send(ws, 3, "Page.navigate", {"url": current})
            replies = 0
            while replies < 128:
                if deadline is not None:
                    deadline.check()
                try:
                    message = self._recv(ws)
                except BrowserUnavailable as exc:
                    if challenge_seen and credentials_sent and _is_receive_timeout(exc):
                        break
                    raise
                except (TimeoutError, OSError) as exc:
                    if challenge_seen and credentials_sent:
                        break
                    raise BrowserUnavailable("Basic Auth challenge timed out") from exc
                if deadline is not None:
                    deadline.check()
                replies += 1
                method = message.get("method")
                raw_params = message.get("params")
                params = raw_params if isinstance(raw_params, dict) else {}
                if method == "Fetch.authRequired":
                    raw_request = params.get("request")
                    request = raw_request if isinstance(raw_request, dict) else {}
                    request_url = request.get("url")
                    challenge_origin = _challenge_origin(params.get("authChallenge"))
                    request_id = params.get("requestId")
                    if (
                        not isinstance(request_id, str)
                        or not request_id
                        or not isinstance(request_url, str)
                        or _origin(request_url) != origin
                        or challenge_origin != origin
                    ):
                        self._cancel_auth(ws, request_id)
                        continue
                    if credentials_sent:
                        self._cancel_auth(ws, request_id)
                        challenge_loop = True
                        break
                    challenge_seen = True
                    if deadline is not None:
                        deadline.check()
                    credentials_sent = True
                    self._send(ws, 4, "Fetch.continueWithAuth", {
                        "requestId": request_id,
                        "authChallengeResponse": {
                            "response": "ProvideCredentials",
                            "username": username,
                            "password": password,
                        },
                    })
                    continue
                if method == "Fetch.requestPaused":
                    request_id = params.get("requestId")
                    if isinstance(request_id, str) and request_id:
                        self._send(ws, 5, "Fetch.continueRequest", {"requestId": request_id})
                    continue
                if method == "Page.loadEventFired" and challenge_seen:
                    continue
            if not challenge_seen:
                raise BrowserUnavailable("Basic Auth challenge was not observed")
        finally:
            try:
                self._send(ws, 99, "Fetch.disable", {})
            except Exception:
                pass
            ws.close()

        url = self._settled_target_url(target_id, fallback=current, deadline=deadline)
        self._state = BasicAuthState(
            target_id,
            url,
            origin if challenge_loop else None,
            (
                not challenge_loop
                and _origin(url) == origin
                and urlsplit(url).path == success_path
            ),
        )

    def _probe(
        self,
        *,
        target_id: str,
        current_url: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> None:
        _validate_target_id(target_id)
        page_origin = _origin(current_url)
        if page_origin is None:
            raise ValueError("Basic Auth probing requires an HTTPS page")
        timeout_s = min(
            self._timeout_s,
            deadline.check() if deadline is not None else self._timeout_s,
        )
        ws = self._ws_factory(self._page_websocket(target_id, deadline=deadline), timeout_s)
        challenge_origin: str | None = None
        try:
            self._enable_interception(ws, page_origin)
            self._send(ws, 3, "Page.navigate", {"url": current_url})
            replies = 0
            while replies < 128:
                if deadline is not None:
                    deadline.check()
                try:
                    message = self._recv(ws)
                except (TimeoutError, OSError) as exc:
                    raise BrowserUnavailable("Basic Auth probe timed out") from exc
                if deadline is not None:
                    deadline.check()
                replies += 1
                if message.get("method") != "Fetch.authRequired":
                    raw_params = message.get("params")
                    params = raw_params if isinstance(raw_params, dict) else {}
                    if message.get("method") == "Fetch.requestPaused":
                        request_id = params.get("requestId")
                        if isinstance(request_id, str) and request_id:
                            self._send(ws, 5, "Fetch.continueRequest", {"requestId": request_id})
                    continue
                raw_params = message.get("params")
                params = raw_params if isinstance(raw_params, dict) else {}
                raw_request = params.get("request")
                request = raw_request if isinstance(raw_request, dict) else {}
                request_url = request.get("url")
                candidate = _challenge_origin(params.get("authChallenge"))
                request_id = params.get("requestId")
                if (
                    isinstance(request_id, str)
                    and request_id
                    and isinstance(request_url, str)
                    and _origin(request_url) == page_origin
                    and candidate == page_origin
                ):
                    challenge_origin = candidate
                    self._cancel_auth(ws, request_id)
                    break
                self._cancel_auth(ws, request_id)
            if challenge_origin is None:
                raise BrowserUnavailable("Basic Auth challenge was not observed")
        finally:
            try:
                self._send(ws, 99, "Fetch.disable", {})
            except Exception:
                pass
            ws.close()
        self._state = BasicAuthState(target_id, current_url, challenge_origin, False)

    def _enable_interception(self, ws: Any, origin: str) -> None:
        self._send(ws, 1, "Fetch.enable", {"handleAuthRequests": True})

    @staticmethod
    def _cancel_auth(ws: Any, request_id: object) -> None:
        if isinstance(request_id, str) and request_id:
            BasicAuthCapability._send(ws, 6, "Fetch.continueWithAuth", {
                "requestId": request_id,
                "authChallengeResponse": {"response": "CancelAuth"},
            })

    def _target_url_or_last(
        self,
        target_id: str,
        *,
        deadline: "BrokerDeadline | None" = None,
    ) -> str:
        _check_deadline(deadline)
        try:
            return self._current_url(target_id=target_id, deadline=deadline)
        except BrowserUnavailable:
            if self._state.target_id == target_id and self._state.url:
                return self._state.url
            raise

    def _settled_target_url(
        self,
        target_id: str,
        *,
        fallback: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> str:
        end = time.monotonic() + min(
            self._timeout_s,
            deadline.check() if deadline is not None else 1.0,
        )
        while True:
            _check_deadline(deadline)
            observed = self._target_url_or_last(target_id, deadline=deadline)
            if _origin(observed) is not None:
                return observed
            if time.monotonic() >= end:
                return fallback
            time.sleep(0.02)

    def _current_url(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> str:
        _check_deadline(deadline)
        target = self._target(target_id)
        url = target.get("url")
        if not isinstance(url, str) or not url:
            raise BrowserUnavailable("target URL is unavailable")
        return url

    def _page_websocket(
        self,
        target_id: str,
        *,
        deadline: "BrokerDeadline | None" = None,
    ) -> str:
        _check_deadline(deadline)
        target = self._target(target_id)
        _check_deadline(deadline)
        ws_url = target.get("webSocketDebuggerUrl")
        if isinstance(ws_url, str):
            if _is_local_websocket(ws_url):
                return ws_url
            raise BrowserUnavailable("target DevTools endpoint is unavailable")
        retry_end = time.monotonic() + min(
            self._timeout_s,
            deadline.check() if deadline is not None else 1.0,
        )
        while time.monotonic() < retry_end:
            _check_deadline(deadline)
            target = self._target(target_id)
            ws_url = target.get("webSocketDebuggerUrl")
            if isinstance(ws_url, str):
                if _is_local_websocket(ws_url):
                    return ws_url
                raise BrowserUnavailable("target DevTools endpoint is unavailable")
            time.sleep(0.02)
        raise BrowserUnavailable("target DevTools endpoint is unavailable")

    def _target(self, target_id: str) -> dict[str, Any]:
        _validate_target_id(target_id)
        raw = self._chrome.json_request("/json/list")
        if not isinstance(raw, list):
            raise BrowserUnavailable("invalid Chrome target response")
        for target in raw:
            if (
                isinstance(target, dict)
                and target.get("type") == "page"
                and target.get("id") == target_id
            ):
                return target
        raise BrowserUnavailable("requested page target is not available")

    @staticmethod
    def _send(ws: Any, command_id: int, method: str, params: dict[str, Any]) -> None:
        ws.send(json.dumps({"id": command_id, "method": method, "params": params}))

    @staticmethod
    def _recv(ws: Any) -> dict[str, Any]:
        raw = ws.recv()
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrowserUnavailable("DevTools returned invalid Basic Auth event") from exc
        if not isinstance(message, dict):
            raise BrowserUnavailable("DevTools returned invalid Basic Auth event")
        if "error" in message:
            raise BrowserUnavailable(
                "DevTools rejected Basic Auth command: "
                + str(message.get("error"))[:256]
            )
        return message


@dataclass(frozen=True)
class BasicAuthState:
    target_id: str
    url: str
    challenge_origin: str | None
    application_authenticated: bool


def _check_deadline(deadline: "BrokerDeadline | None") -> None:
    if deadline is not None:
        deadline.check()


def _is_receive_timeout(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, (TimeoutError, socket.timeout)):
            return True
        current = current.__cause__
    return False


def _validate_target_id(target_id: str) -> None:
    if (
        not isinstance(target_id, str)
        or not target_id
        or len(target_id) > 256
        or any(char in target_id for char in ("\r", "\n", "\x00"))
    ):
        raise ValueError("Basic Auth target_id is invalid")


def _validate_success_path(success_path: str) -> None:
    if (
        not isinstance(success_path, str)
        or not success_path.startswith("/")
        or success_path.startswith("//")
        or "?" in success_path
        or "#" in success_path
        or len(success_path) > 2048
    ):
        raise ValueError("Basic Auth success_path is invalid")


def _validate_credential(origin: str, username: str, password: str) -> None:
    if _origin(origin) != origin:
        raise ValueError("Basic Auth origin must be an exact HTTPS origin")
    for value, maximum, label in (
        (username, 512, "username"),
        (password, 4096, "password"),
    ):
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise ValueError(f"Basic Auth {label} is invalid")
        if any(char in value for char in ("\r", "\n", "\x00")):
            raise ValueError(f"Basic Auth {label} contains forbidden characters")


def _redact_url(url: str) -> str:
    """Keep URL path for broker state; never expose query or fragment."""
    if not isinstance(url, str) or len(url.encode("utf-8")) > 2048:
        raise BrowserUnavailable("invalid Basic Auth state URL")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise BrowserUnavailable("invalid Basic Auth state URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise BrowserUnavailable("invalid Basic Auth state URL")
    redacted = parsed._replace(query="", fragment="").geturl()
    if len(redacted.encode("utf-8")) > 2048:
        raise BrowserUnavailable("Basic Auth state URL is too large")
    return redacted


def _is_local_websocket(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "ws"
        and hostname in {"127.0.0.1", "localhost", "::1"}
        and port is not None
        and 1 <= port <= 65535
        and bool(parsed.path)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _origin(url: str) -> str | None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return f"https://{parsed.netloc}"


def _challenge_origin(challenge: object) -> str | None:
    if not isinstance(challenge, dict) or str(challenge.get("scheme", "")).lower() != "basic":
        return None
    origin = challenge.get("origin")
    return _origin(origin) if isinstance(origin, str) else None


__all__ = ["BasicAuthCapability"]
