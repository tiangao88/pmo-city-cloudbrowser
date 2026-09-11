"""Browser process API with explicit page action capabilities."""

from __future__ import annotations

import hmac
import json
import math
import os
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol
from urllib.parse import parse_qs, urlsplit

if TYPE_CHECKING:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline

from cloudbrowser.credential_broker.deadline import (
    BrokerDeadline,
    BrokerDeadlineExceeded,
    accepts_keyword,
)

from .browser_process import BrowserProcess
from .chrome_adapter import ChromeBrowserAdapter
from .transport import BrowserUnavailable

_MAX_BODY = 8192
_MAX_RESPONSE = 64 * 1024
_MAX_BROKER_DEADLINE_S = 30.0
_DEFAULT_BROKER_DEADLINE_S = 30.0
_BROKER_DEADLINE_HEADER = "X-CB-Broker-Deadline-S"


class BrokerAuthentikCapability(Protocol):
    def state(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | None]: ...

    def begin(
        self,
        *,
        target_id: str,
        entry_url: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> None: ...

    def identification(
        self,
        *,
        target_id: str,
        username: str,
        password: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str]: ...

    def proof(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | None]: ...


class BrokerBasicAuthCapability(Protocol):
    def state(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | bool | None]: ...

    def probe(
        self,
        *,
        target_id: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str | bool | None]: ...

    def submit(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
        deadline: "BrokerDeadline | None" = None,
    ) -> None: ...


def _as_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BrowserUnavailable("invalid broker capability response")
    return value


def _public_state_url(value: object) -> str:
    if not isinstance(value, str):
        raise BrowserUnavailable("invalid Basic Auth state URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise BrowserUnavailable("invalid Basic Auth state URL")
    return parsed._replace(query="", fragment="").geturl()


def _public_state_origin(value: object) -> str:
    if not isinstance(value, str):
        raise BrowserUnavailable("invalid Basic Auth challenge origin")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise BrowserUnavailable("invalid Basic Auth challenge origin")
    return f"https://{parsed.netloc}"


def _rebind_component(component: object, binding: object) -> None:
    """Rotate a component, tolerating only its prior two-field test contract."""
    try:
        component.rebind(
            binding.principal_id,
            binding.generation,
            profile_id=binding.profile_id,
            browser_id=binding.browser_id,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        component.rebind(binding.principal_id, binding.generation)


def create_browser_server(
    adapter: ChromeBrowserAdapter,
    process: BrowserProcess,
    *,
    instance_id: str,
    release_version: str,
    address: tuple[str, int] = ("127.0.0.1", 9230),
    binding_listener: Callable[[Any], None] | None = None,
    basic_auth: BrokerBasicAuthCapability | None = None,
    authentik: BrokerAuthentikCapability | None = None,
    broker_submit_secret: str = "",
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> ThreadingHTTPServer:
    """Create the restricted browser API consumed by supervisor and agent control.

    ``binding_listener`` (optional) is invoked with the parsed
    ``BrowserBinding`` after a successful trusted-secret-gated binding push;
    the browser service uses it to rotate download attribution to the
    newly adopted identity.
    """
    if not instance_id or not release_version:
        raise ValueError("instance_id and release_version are required")
    if not callable(monotonic_clock):
        raise ValueError("monotonic_clock must be callable")
    lifecycle_gate = threading.RLock()

    def require_agent_binding(handler: BaseHTTPRequestHandler) -> None:
        binding = getattr(adapter, "binding", None)
        from .lifecycle import BrowserBinding

        if not isinstance(binding, BrowserBinding) or (
            handler.headers.get("X-CB-Principal") != binding.principal_id
            or handler.headers.get("X-CB-Generation") != binding.generation
        ):
            raise BrowserUnavailable("agent browser binding mismatch")

    def serialized_http_operation(operation: Callable) -> Callable:
        @wraps(operation)
        def guarded(handler: Any, *args: object, **kwargs: object) -> object:
            receipt = float(monotonic_clock())
            if not math.isfinite(receipt):
                raise ValueError("invalid browser monotonic clock")
            handler._request_received_monotonic = receipt
            with lifecycle_gate:
                return operation(handler, *args, **kwargs)

        return guarded

    class SerializedBrowserServer(ThreadingHTTPServer):
        daemon_threads = True

        def server_close(self) -> None:
            with lifecycle_gate:
                try:
                    process.stop()
                except (AttributeError, BrowserUnavailable):
                    pass
                super().server_close()

    class Handler(BaseHTTPRequestHandler):
        def _binding_identity(self) -> tuple[str, str]:
            from cloudbrowser.browser_slots import BrowserBinding

            binding = getattr(adapter, "binding", None)
            if isinstance(binding, BrowserBinding):
                return binding.profile_id, binding.browser_id
            return (
                os.environ.get("CB_PROFILE_ID", "profile-unassigned"),
                os.environ.get("CB_BROWSER_ID", "browser-unassigned"),
            )

        @serialized_http_operation
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                parsed = urlsplit(self.path)
                if parsed.path == "/agent/pages/info":
                    require_agent_binding(self)
                    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2) if parsed.query else {}
                    if set(query) - {"target_tab_id", "selector"}:
                        raise ValueError("invalid page-info query")
                    target_values = query.get("target_tab_id", [])
                    if len(target_values) != 1:
                        raise ValueError("target_tab_id is required")
                    selector_values = query.get("selector", [])
                    if len(selector_values) > 1:
                        raise ValueError("selector is duplicated")
                    target_tab_id = target_values[0]
                    selector = selector_values[0] if selector_values else None
                    from .page_actions import _validate_selector, _validate_target_id

                    _validate_target_id(target_tab_id)
                    if selector is not None:
                        _validate_selector(selector)
                    self._send_json(200, adapter.page_info(target_tab_id, selector))
                    return
                if self.path in ("/browser/readiness", "/agent/readiness"):
                    if self.path == "/agent/readiness":
                        require_agent_binding(self)
                    ready = adapter.readiness()
                    healthy = process.readiness()
                    profile_id, browser_id = self._binding_identity()
                    self._send_json(
                        200 if healthy else 503,
                        {
                            "owner": ready.owner,
                            "generation": ready.generation,
                            "profile_id": profile_id,
                            "browser_id": browser_id,
                            "cdp_ok": ready.cdp_ok and healthy,
                            "browser_state": process.state,
                        },
                    )
                    return
                if self.path == "/browser/health":
                    healthy = process.readiness()
                    state = process.state
                    if state == "stopped":
                        status_code, service_status = 200, "ok"
                    else:
                        status_code = 200 if healthy else 503
                        service_status = "ok" if healthy else "degraded"
                    self._send_json(
                        status_code,
                        {
                            "status": service_status,
                            "component": "browser",
                            "instance_id": instance_id,
                            "release_version": release_version,
                            "browser_state": state,
                        },
                    )
                    return
                if self.path in ("/browser/pages", "/agent/pages"):
                    if self.path == "/agent/pages":
                        require_agent_binding(self)
                    if self.path == "/browser/pages":
                        self._send_json(200, {"urls": adapter.list_page_urls()})
                    else:
                        from .page_actions import bounded_page_targets

                        self._send_json(
                            200,
                            {"pages": bounded_page_targets(adapter.chrome.json_request("/json/list"))},
                        )
                    return
                if self.path == "/broker/basic/state":
                    self.send_error(405)
                    return
                self.send_error(404)
            except BrowserUnavailable:
                self._send_json(503, {"ok": False, "error_code": "browser_unavailable"})
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"ok": False, "error_code": "invalid_request"})

        @serialized_http_operation
        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                if self.path == "/browser/binding":
                    self._handle_binding_push()
                    return
                if self.path == "/browser/start":
                    with lifecycle_gate:
                        adapter.start()
                elif self.path == "/browser/stop":
                    with lifecycle_gate:
                        adapter.stop()
                elif self.path == "/browser/pages/open":
                    adapter.open_page(self._read_text())
                elif self.path == "/agent/pages/open":
                    require_agent_binding(self)
                    payload = json.loads(self._read_text())
                    if (
                        not isinstance(payload, dict)
                        or set(payload) != {"url"}
                        or not isinstance(payload["url"], str)
                    ):
                        raise ValueError("tab-open payload is invalid")
                    self._send_json(200, {"page": adapter.open_page(payload["url"])})
                    return
                elif self.path == "/browser/pages/close-empty":
                    adapter.close_empty_pages()
                elif self.path == "/agent/pages/navigate":
                    require_agent_binding(self)
                    target_tab_id, url = self._read_page_action_payload()
                    adapter.navigate(target_tab_id, url)
                elif self.path == "/agent/pages/click":
                    require_agent_binding(self)
                    target_tab_id, selector = self._read_page_action_payload()
                    adapter.click(target_tab_id, selector)
                elif self.path == "/agent/pages/type":
                    require_agent_binding(self)
                    target_tab_id, selector, text = self._read_page_type_payload()
                    adapter.type_text(target_tab_id, selector, text)
                elif self.path.startswith("/broker/authentik/"):
                    if not self._broker_authorized() or authentik is None:
                        self._send_json(401, {"ok": False, "error_code": "unauthorized"})
                        return
                    payload = json.loads(self._read_text())
                    if not isinstance(payload, dict) or not isinstance(payload.get("target_id"), str):
                        raise ValueError("Authentik payload is invalid")
                    deadline = self._broker_deadline()
                    target_id = payload["target_id"]
                    if self.path == "/broker/authentik/state":
                        self._send_json(
                            200,
                            _as_mapping(
                                self._invoke_broker(
                                    authentik.state,
                                    target_id=target_id,
                                    deadline=deadline,
                                )
                            ),
                        )
                        return
                    if self.path == "/broker/authentik/begin":
                        entry_url = payload.get("entry_url")
                        if not isinstance(entry_url, str):
                            raise ValueError("Authentik entry URL is invalid")
                        self._invoke_broker(
                            authentik.begin,
                            target_id=target_id,
                            entry_url=entry_url,
                            deadline=deadline,
                        )
                    elif self.path == "/broker/authentik/identification":
                        username, password = payload.get("username"), payload.get("password")
                        if not isinstance(username, str) or not isinstance(password, str):
                            raise ValueError("Authentik identification payload is invalid")
                        self._send_json(
                            200,
                            _as_mapping(
                                self._invoke_broker(
                                    authentik.identification,
                                    target_id=target_id,
                                    username=username,
                                    password=password,
                                    deadline=deadline,
                                )
                            ),
                        )
                        return
                    elif self.path == "/broker/authentik/proof":
                        self._send_json(
                            200,
                            _as_mapping(
                                self._invoke_broker(
                                    authentik.proof,
                                    target_id=target_id,
                                    deadline=deadline,
                                )
                            ),
                        )
                        return
                    else:
                        self.send_error(404)
                        return
                elif self.path == "/broker/basic/state":
                    if not self._broker_authorized() or basic_auth is None:
                        self._send_json(401, {"ok": False, "error_code": "unauthorized"})
                        return
                    payload = json.loads(self._read_text())
                    if not isinstance(payload, dict):
                        raise ValueError("Basic Auth state payload must be an object")
                    target_id = payload.get("target_id")
                    if not isinstance(target_id, str):
                        raise ValueError("Basic Auth target_id is invalid")
                    deadline = self._broker_deadline()
                    probe = getattr(basic_auth, "probe", None)
                    probe_result = (
                        self._invoke_broker(
                            probe,
                            target_id=target_id,
                            deadline=deadline,
                        )
                        if callable(probe)
                        else self._invoke_broker(
                            basic_auth.state,
                            target_id=target_id,
                            deadline=deadline,
                        )
                    )
                    if not isinstance(probe_result, Mapping):
                        raise BrowserUnavailable("invalid Basic Auth probe state")
                    result = dict(probe_result)
                    result["url"] = _public_state_url(result.get("url"))
                    if result.get("challenge_origin") is not None:
                        result["challenge_origin"] = _public_state_origin(result.get("challenge_origin"))
                    self._send_json(200, result)
                    return
                elif self.path == "/broker/basic/submit":
                    if not self._broker_authorized() or basic_auth is None:
                        self._send_json(401, {"ok": False, "error_code": "unauthorized"})
                        return
                    payload = json.loads(self._read_text())
                    if not isinstance(payload, dict):
                        raise ValueError("Basic Auth payload must be an object")
                    origin = payload.get("origin")
                    username = payload.get("username")
                    password = payload.get("password")
                    target_id = payload.get("target_id")
                    success_path = payload.get("success_path")
                    if not all(
                        isinstance(value, str)
                        for value in (origin, username, password, target_id, success_path)
                    ):
                        raise ValueError("Basic Auth payload is invalid")
                    assert isinstance(origin, str)
                    assert isinstance(username, str)
                    assert isinstance(password, str)
                    assert isinstance(target_id, str)
                    assert isinstance(success_path, str)
                    deadline = self._broker_deadline()
                    self._invoke_broker(
                        basic_auth.submit,
                        origin,
                        username,
                        password,
                        target_id=target_id,
                        success_path=success_path,
                        deadline=deadline,
                    )
                else:
                    self.send_error(404)
                    return
                self._send_json(200, {"ok": True})
            except BrokerDeadlineExceeded:
                self._send_json(504, {"ok": False, "error_code": "deadline_exceeded"})
            except (BrowserUnavailable, ValueError, UnicodeDecodeError):
                self._send_json(503, {"ok": False, "error_code": "browser_operation_failed"})

        def _handle_binding_push(self) -> None:
            """Adopt a server-minted binding (trusted-secret gated).

            Only a stopped browser may be rebound, mirroring the lifecycle
            rule; the adapter and process are rebuilt for the new identity.
            """

            import os

            from cloudbrowser.browser_service import parse_binding_push

            expected = os.environ.get("CB_ROUTER_SHARED_SECRET")
            provided = self.headers.get("X-CB-Trusted-Secret")
            if not expected or not provided:
                self._send_json(403, {"ok": False, "error_code": "binding_not_authorized"})
                return
            try:
                payload = json.loads(self._read_text())
                binding = parse_binding_push(payload, provided_secret=provided)
            except PermissionError:
                # parse_binding_push gates the trusted secret before payload
                # inspection; a mismatch must be a bounded 403, never a dead
                # handler thread.
                self._send_json(403, {"ok": False, "error_code": "binding_not_authorized"})
                return
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error_code": "invalid_binding"})
                return
            with lifecycle_gate:
                if process.state != "stopped":
                    self._send_json(409, {"ok": False, "error_code": "browser_not_stopped"})
                    return
                _rebind_component(process, binding)
                _rebind_component(adapter, binding)
            if binding_listener is not None:
                try:
                    binding_listener(binding)
                except Exception:  # noqa: BLE001 - listener must never abort the push
                    # The identity rebind already happened; a listener fault
                    # (e.g. download-watcher maintenance) must not turn a
                    # successful adoption into a dead handler/connection.
                    self.log_error("binding listener raised; push still accepted")
            self._send_json(200, {"ok": True})

        def _broker_authorized(self) -> bool:
            candidate = self.headers.get("X-CB-Broker-Secret", "")
            return bool(
                (basic_auth is not None or authentik is not None)
                and len(broker_submit_secret) >= 16
                and hmac.compare_digest(candidate, broker_submit_secret)
            )

        def _broker_deadline(self) -> "BrokerDeadline":
            raw = self.headers.get(_BROKER_DEADLINE_HEADER)
            if raw is None:
                budget_s = _DEFAULT_BROKER_DEADLINE_S
            else:
                try:
                    budget_s = float(raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid broker deadline") from exc
                if not math.isfinite(budget_s) or budget_s <= 0:
                    raise ValueError("invalid broker deadline")
                budget_s = min(budget_s, _MAX_BROKER_DEADLINE_S)
            receipt = getattr(self, "_request_received_monotonic", None)
            if not isinstance(receipt, (int, float)) or not math.isfinite(float(receipt)):
                raise ValueError("invalid broker deadline receipt")
            return BrokerDeadline.from_receipt(
                receipt_monotonic=float(receipt),
                budget_s=budget_s,
                monotonic_clock=monotonic_clock,
            )

        def _invoke_broker(
            self,
            callable_object: Callable[..., object],
            /,
            *args: object,
            deadline: "BrokerDeadline",
            **kwargs: object,
        ) -> object:
            deadline.check()
            if accepts_keyword(callable_object, "deadline"):
                kwargs["deadline"] = deadline
            result = callable_object(*args, **kwargs)
            deadline.check()
            return result
        def _read_text(self) -> str:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid body length") from exc
            if length <= 0 or length > _MAX_BODY:
                raise ValueError("invalid body length")
            return self.rfile.read(length).decode("utf-8")

        def _read_page_action_payload(self) -> tuple[str, str]:
            payload = json.loads(self._read_text())
            if not isinstance(payload, dict) or set(payload) != {"target_tab_id", "value"}:
                raise ValueError("page action payload is invalid")
            target_tab_id, value = payload.get("target_tab_id"), payload.get("value")
            from .page_actions import _validate_target_id

            _validate_target_id(target_tab_id)
            if not isinstance(value, str) or not value:
                raise ValueError("page action value is invalid")
            return target_tab_id, value

        def _read_page_type_payload(self) -> tuple[str, str, str]:
            payload = json.loads(self._read_text())
            if not isinstance(payload, dict) or set(payload) != {"target_tab_id", "selector", "text"}:
                raise ValueError("page type payload is invalid")
            target_tab_id = payload.get("target_tab_id")
            selector = payload.get("selector")
            text = payload.get("text")
            from .page_actions import _validate_selector, _validate_target_id

            _validate_target_id(target_tab_id)
            _validate_selector(selector)
            if not isinstance(text, str) or not text:
                raise ValueError("page type text is invalid")
            return target_tab_id, selector, text

        def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if len(body) > _MAX_RESPONSE:
                status = 503
                body = b'{"ok":false,"error_code":"response_too_large"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return SerializedBrowserServer(address, Handler)
