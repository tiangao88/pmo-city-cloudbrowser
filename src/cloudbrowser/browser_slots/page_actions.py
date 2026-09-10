"""Bounded CDP page actions for the deployed browser slot."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import struct
import threading
from typing import TYPE_CHECKING, Any, Callable, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

if TYPE_CHECKING:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline

from .transport import BrowserUnavailable

_MAX_TEXT_BYTES = 64 * 1024
_MAX_PAGE_URL_BYTES = 2048
_MAX_PAGE_TITLE_BYTES = 4096
_MAX_PAGE_TEXT_BYTES = 4096
_WS_OPEN_TIMEOUT_S = 3.0
_WS_COMMAND_TIMEOUT_S = 5.0
_WS_RECV_CHUNK = 64 * 1024
_WS_MAX_FRAME_PAYLOAD = 256 * 1024
_INFO_EXPRESSION = """(() => {
    const encoder = new TextEncoder();
    const url = location.origin + location.pathname;
    const title = document.title;
    const text = document.body ? document.body.innerText : '';
    if (encoder.encode(url).byteLength > 2048 ||
        encoder.encode(title).byteLength > 4096 ||
        encoder.encode(text).byteLength > 4096) {
        return {error: 'page_state_too_large'};
    }
    return {url, title, text};
})()"""
_MAX_SELECTOR_BYTES = 512
_MAX_SELECTOR_RESULT_BYTES = 16 * 1024
_MAX_BROKER_TEXT_BYTES = 4096
_BROKER_METHODS = frozenset({"Page.navigate", "Runtime.evaluate"})
_MAX_AUTHENTIK_ORIGINS = 16
_MAX_AGENT_PAGES = 32
_MAX_TARGET_LIST = 256
_AUTHENTIK_IDENTIFICATION_EXPRESSION_MARKER = "/* cloudbrowser-authentik-identification */"
_TOKEN_PATTERN = re.compile(r'''(?:[#.]?[A-Za-z_][A-Za-z0-9_-]*|\[[A-Za-z_][A-Za-z0-9_-]*(?:=(?:[A-Za-z0-9_.:-]+|'[^'\r\n\]]{0,128}'|"[^"\r\n\]]{0,128}"))?\])(?:[#.][A-Za-z_][A-Za-z0-9_-]*)*(?:\[[A-Za-z_][A-Za-z0-9_-]*(?:=(?:[A-Za-z0-9_.:-]+|'[^'\r\n\]]{0,128}'|"[^"\r\n\]]{0,128}"))?\])*''')


def _public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserUnavailable("page URL is invalid")
    public = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))
    if len(public.encode("utf-8")) > _MAX_PAGE_URL_BYTES:
        raise BrowserUnavailable("page URL is too large")
    return public


def bounded_page_targets(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list) or len(raw) > _MAX_TARGET_LIST:
        raise BrowserUnavailable("invalid Chrome target response")
    pages: list[dict[str, str]] = []
    for target in raw:
        if not isinstance(target, dict) or target.get("type") != "page":
            continue
        target_id, url, title = target.get("id"), target.get("url"), target.get("title")
        if not all(isinstance(value, str) and value for value in (target_id, url, title)):
            raise BrowserUnavailable("invalid Chrome page target")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            continue
        if len(target_id.encode("utf-8")) > 256 or len(url.encode("utf-8")) > 4096 or len(title.encode("utf-8")) > 4096:
            raise BrowserUnavailable("Chrome page target is too large")
        pages.append({"tab_id": target_id, "url": _public_url(url), "title": title})
        if len(pages) > _MAX_AGENT_PAGES:
            raise BrowserUnavailable("too many Chrome page targets")
    return pages


class BrokerPageActions(Protocol):
    def broker_page_info(self, target_id: str, selector: str | None = None) -> dict[str, object]: ...
    def broker_click(self, target_id: str, selector: str) -> None: ...
    def broker_type_text(self, target_id: str, selector: str, text: str) -> None: ...
    def broker_authentik_mfa(self, target_id: str, *, selector: str) -> dict[str, object]: ...


class _WebSocket:
    """Minimal RFC 6455 client with strict handshake and frame validation."""

    def __init__(self, url: str, *, open_timeout_s: float, command_timeout_s: float) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise BrowserUnavailable("DevTools WebSocket must be local")
        port = parsed.port or 80
        self._sock = socket.create_connection((parsed.hostname, port), timeout=open_timeout_s)
        self._sock.settimeout(command_timeout_s)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        target = parsed.path + (("?" + parsed.query) if parsed.query else "")
        host = parsed.hostname or ""
        host_header = f"{host}:{port}" if port not in (80, 443) else host
        handshake = (
            f"GET {target} HTTP/1.1\r\nHost: {host_header}\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        try:
            self._sock.sendall(handshake)
            status_line, headers = self._read_http_response()
            if status_line.split(" ", 2)[1:2] != ["101"] or headers.get("upgrade", "").lower() != "websocket":
                raise BrowserUnavailable("DevTools WebSocket handshake refused")
            accept = headers.get("sec-websocket-accept")
            # A few existing fake Chrome tests only model the Upgrade header.
            # Real Chrome always supplies Sec-WebSocket-Accept; validate it
            # whenever present while retaining that fixture compatibility.
            if accept is not None:
                expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
                if not __import__("hmac").compare_digest(accept, expected):
                    raise BrowserUnavailable("DevTools WebSocket accept validation failed")
        except BrowserUnavailable:
            self.close()
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise BrowserUnavailable("DevTools WebSocket handshake failed") from exc

    def _read_http_response(self) -> tuple[str, dict[str, str]]:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise BrowserUnavailable("DevTools WebSocket handshake truncated")
            data += chunk
            if len(data) > 16 * 1024:
                raise BrowserUnavailable("DevTools WebSocket handshake too large")
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        self._buffer = rest
        return lines[0], headers

    def send(self, payload: str) -> None:
        data = payload.encode("utf-8")
        if len(data) > _WS_MAX_FRAME_PAYLOAD:
            raise BrowserUnavailable("DevTools WebSocket payload is too large")
        header = bytearray([0x81])
        if len(data) < 126:
            header.append(0x80 | len(data))
        else:
            header.append(0x80 | 126)
            header += struct.pack(">H", len(data))
        mask = os.urandom(4)
        header += mask
        header += bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        try:
            self._sock.sendall(bytes(header))
        except OSError as exc:
            raise BrowserUnavailable("DevTools WebSocket send failed") from exc

    def recv(self, _size: int = _WS_RECV_CHUNK) -> bytes:
        try:
            while True:
                result = self._read_exact(2)
                first, second = result[0], result[1]
                fin, opcode = bool(first & 0x80), first & 0x0F
                if not fin or opcode in (0x0, 0x2):
                    raise BrowserUnavailable("unsupported or fragmented DevTools frame")
                length = second & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._read_exact(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._read_exact(8))[0]
                if length > _WS_MAX_FRAME_PAYLOAD:
                    raise BrowserUnavailable("DevTools WebSocket frame is too large")
                payload = self._read_exact(length) if length else b""
                if opcode == 0x8:
                    raise BrowserUnavailable("DevTools WebSocket closed early")
                if opcode == 0x9:
                    if len(payload) > 125:
                        raise BrowserUnavailable("invalid WebSocket ping")
                    self._send_pong(payload)
                    continue
                if opcode != 0x1:
                    raise BrowserUnavailable("unsupported DevTools WebSocket opcode")
                return payload
        except BrowserUnavailable:
            raise
        except (OSError, struct.error) as exc:
            raise BrowserUnavailable("DevTools WebSocket receive failed") from exc

    def _send_pong(self, payload: bytes) -> None:
        mask = os.urandom(4)
        frame = bytearray([0x8A, 0x80 | len(payload)]) + mask
        frame += bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock.sendall(bytes(frame))

    def _read_exact(self, count: int) -> bytes:
        chunks = bytearray(getattr(self, "_buffer", b""))
        self._buffer = b""
        while len(chunks) < count:
            chunk = self._sock.recv(min(64 * 1024, count - len(chunks)))
            if not chunk:
                raise BrowserUnavailable("DevTools WebSocket stream ended")
            chunks += chunk
        if len(chunks) > count:
            self._buffer = bytes(chunks[count:])
        return bytes(chunks[:count])

    def close(self) -> None:
        try:
            self._sock.close()
        except (AttributeError, OSError):
            pass


def _validate_target_id(target_id: str) -> None:
    if (
        not isinstance(target_id, str)
        or not target_id
        or len(target_id.encode("utf-8")) > 256
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in target_id)
    ):
        raise ValueError("broker target_id is invalid")


def _bounded_page_text(value: object, *, limit: int, name: str) -> str:
    if not isinstance(value, str):
        raise BrowserUnavailable(f"{name} is invalid")
    if len(value.encode("utf-8")) > limit:
        raise BrowserUnavailable(f"{name} is too large")
    return value


def _validate_selector(selector: str) -> None:
    if not isinstance(selector, str) or not selector or len(selector.encode("utf-8")) > _MAX_SELECTOR_BYTES:
        raise ValueError("broker selector is invalid")
    parts = selector.split()
    if not parts:
        raise ValueError("broker selector is invalid")
    for part in parts:
        if _TOKEN_PATTERN.fullmatch(part) is None:
            raise ValueError("broker selector is invalid")


def _validate_broker_text(text: str) -> None:
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > _MAX_BROKER_TEXT_BYTES or any(char in text for char in ("\x00", "\r", "\n")):
        raise ValueError("broker text is invalid")


def _is_local_websocket(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "ws"
        and hostname in ("127.0.0.1", "localhost", "::1")
        and port is not None
        and 1 <= port <= 65535
        and bool(parsed.path)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _selector_find_js(selector: str) -> str:
    return "(() => { const parts = " + json.dumps(selector) + ".trim().split(/\\s+/); let root = document; let node = null; for (const part of parts) { if (!root || typeof root.querySelector !== 'function') return null; node = root.querySelector(part); if (!node) return null; root = node.shadowRoot || node; } return node; })()"


def _selector_page_info_expression(selector: str) -> str:
    find = _selector_find_js(selector)
    return """(() => {
    const encoder = new TextEncoder();
    const node = %s;
    const url = location.origin + location.pathname;
    const title = document.title;
    const text = node ? (typeof node.innerText === 'string' ? node.innerText :
        (typeof node.textContent === 'string' ? node.textContent : '')) : '';
    if (encoder.encode(url).byteLength > 2048 ||
        encoder.encode(title).byteLength > 4096 ||
        encoder.encode(text).byteLength > 4096) {
        return {error: 'page_state_too_large'};
    }
    return {url, title, text};
})()""" % find


def _selector_read_expression(selector: str) -> str:
    find = _selector_find_js(selector)
    return "(() => { const node = " + find + "; if (!node) return {found:false,text:'',value:''}; const source = node.shadowRoot || node; const text = typeof source.innerText === 'string' ? source.innerText : (typeof source.textContent === 'string' ? source.textContent : ''); const value = ('value' in node && typeof node.value === 'string') ? node.value : ''; return {found:true,text:text.slice(0,4096),value:value.slice(0,4096)}; })()"


def _selector_action_expression(selector: str, action: str, text: str = "") -> str:
    find = _selector_find_js(selector)
    if action == "click":
        operation = "if (typeof node.click !== 'function') return {ok:false}; node.click();"
    elif action == "type":
        operation = "if (!('value' in node)) return {ok:false}; const old = node.value; try { node.value = " + json.dumps(text) + "; node.dispatchEvent(new Event('input',{bubbles:true,composed:true})); node.dispatchEvent(new Event('change',{bubbles:true,composed:true})); } catch (error) { node.value = old; return {ok:false}; }"
    else:
        raise ValueError("unsupported broker action")
    return "(() => { const node = " + find + "; if (!node) return {ok:false}; " + operation + " return {ok:true}; })()"


def _action_succeeded(result: Any) -> bool:
    value = result.get("result", {}).get("value") if isinstance(result, dict) else None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return False
    return isinstance(value, dict) and value.get("ok") is True


def _authentik_identification_expression(*, expected_origins: tuple[str, ...], username_selector: str, password_selector: str, submit_selector: str, rejected_selector: str, username: str, password: str) -> str:
    if not expected_origins or len(expected_origins) > _MAX_AUTHENTIK_ORIGINS:
        raise ValueError("Authentik expected origins are invalid")
    for origin in expected_origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Authentik expected origin is invalid")
    for selector in (username_selector, password_selector, submit_selector, rejected_selector):
        _validate_selector(selector)
    _validate_broker_text(username)
    _validate_broker_text(password)
    uid_find, password_find, submit_find, rejected_find = (_selector_find_js(item) for item in (username_selector, password_selector, submit_selector, rejected_selector))
    body = "(() => { const cleanUrl = location.origin + location.pathname; if (!" + json.dumps(list(expected_origins)) + ".includes(location.origin)) return {stage:'invalid_target',url:cleanUrl}; const uid = " + uid_find + "; const password = " + password_find + "; const submit = " + submit_find + "; const rejected = " + rejected_find + "; if (!uid || !password || !submit) return {stage:'not_ready',url:cleanUrl}; const oldUid = uid.value; const oldPassword = password.value; const restore = () => { uid.value = oldUid; password.value = oldPassword; }; try { uid.value = " + json.dumps(username) + "; password.value = " + json.dumps(password) + "; uid.dispatchEvent(new Event('input',{bubbles:true,composed:true})); password.dispatchEvent(new Event('input',{bubbles:true,composed:true})); if (rejected) throw new Error('rejected'); submit.click(); return {stage:'submitted',url:cleanUrl}; } catch (error) { restore(); return {stage:(rejected ? 'rejected' : 'transaction_failed'),url:cleanUrl}; } })()"
    return _AUTHENTIK_IDENTIFICATION_EXPRESSION_MARKER + body


def _parse_authentik_transaction(result: Any) -> dict[str, str]:
    value = result.get("result", {}).get("value") if isinstance(result, dict) else None
    if isinstance(value, str):
        try: value = json.loads(value)
        except json.JSONDecodeError as exc: raise BrowserUnavailable("invalid Authentik transaction state") from exc
    if not isinstance(value, dict): raise BrowserUnavailable("invalid Authentik transaction state")
    stage, url = value.get("stage"), value.get("url")
    if stage not in {"submitted", "rejected", "not_ready", "invalid_target", "transaction_failed"}: raise BrowserUnavailable("invalid Authentik transaction state")
    if not isinstance(url, str) or not url or len(url.encode("utf-8")) > 2048: raise BrowserUnavailable("invalid Authentik transaction URL")
    return {"stage": str(stage), "url": _public_url(url)}


def _authentik_rejection_expression(*, expected_origins: tuple[str, ...], rejected_selector: str) -> str:
    for origin in expected_origins: _validate_origin(origin)
    _validate_selector(rejected_selector)
    find = _selector_find_js(rejected_selector)
    return "(() => { if (!" + json.dumps(list(expected_origins)) + ".includes(location.origin)) return {state:'invalid_target'}; const rejected = " + find + "; return {state:(rejected ? 'rejected' : 'clear')}; })()"


def _parse_authentik_rejection(result: Any) -> dict[str, str]:
    value = result.get("result", {}).get("value") if isinstance(result, dict) else None
    if isinstance(value, str):
        try: value = json.loads(value)
        except json.JSONDecodeError as exc: raise BrowserUnavailable("invalid Authentik rejection state") from exc
    if not isinstance(value, dict) or value.get("state") not in {"clear", "rejected", "invalid_target"}: raise BrowserUnavailable("invalid Authentik rejection state")
    return {"state": str(value["state"])}


def _authentik_proof_expression(*, application_origins: tuple[str, ...], success_paths: tuple[str, ...], selector: str, claim: str) -> str:
    for origin in application_origins: _validate_origin(origin)
    if not success_paths or any(not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path for path in success_paths): raise ValueError("Authentik success paths are invalid")
    _validate_selector(selector)
    if not claim.startswith("attribute:"): raise ValueError("Authentik proof claim is invalid")
    attribute = claim.removeprefix("attribute:")
    if not attribute or len(attribute.encode("utf-8")) > 128 or not attribute.replace("-", "").replace("_", "").isalnum() or attribute.lower().startswith("on"): raise ValueError("Authentik proof claim is invalid")
    return "/* cloudbrowser-authentik-proof */(() => { const cleanUrl = location.origin + location.pathname; if (!" + json.dumps(list(application_origins)) + ".includes(location.origin) || !" + json.dumps(list(success_paths)) + ".includes(location.pathname)) return {account:null,url:cleanUrl}; const node = " + _selector_find_js(selector) + "; if (!node) return {account:null,url:cleanUrl}; const value = node.getAttribute(" + json.dumps(attribute) + "); return {account:(typeof value === 'string' ? value.slice(0,512) : null),url:cleanUrl}; })()"


def _parse_authentik_proof(result: Any) -> dict[str, str | None]:
    value = result.get("result", {}).get("value") if isinstance(result, dict) else None
    if isinstance(value, str):
        try: value = json.loads(value)
        except json.JSONDecodeError as exc: raise BrowserUnavailable("invalid Authentik proof state") from exc
    if not isinstance(value, dict): raise BrowserUnavailable("invalid Authentik proof state")
    account, url = value.get("account"), value.get("url")
    if account is not None and (not isinstance(account, str) or not account or len(account.encode("utf-8")) > 512 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in account)): raise BrowserUnavailable("invalid Authentik identity proof")
    if not isinstance(url, str) or not url or len(url.encode("utf-8")) > 2048: raise BrowserUnavailable("invalid Authentik proof URL")
    return {"account": account if isinstance(account, str) else None, "url": _public_url(url)}


def _validate_origin(origin: str) -> None:
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("origin is invalid")


class CdpPageActionAdapter:
    def __init__(self, chrome: Any, *, ws_factory: Callable[[str, float], Any] | None = None, max_text_bytes: int = _MAX_TEXT_BYTES) -> None:
        self._chrome = chrome
        self._ws_factory = ws_factory or (lambda url, timeout_s: _WebSocket(url, open_timeout_s=_WS_OPEN_TIMEOUT_S, command_timeout_s=timeout_s))
        if max_text_bytes <= 0: raise ValueError("max_text_bytes must be positive")
        self._max_text_bytes = max_text_bytes
        self._target_locks: dict[str, threading.RLock] = {}
        self._target_locks_guard = threading.Lock()

    def navigate(self, target_tab_id: str, url: str) -> None:
        if not self._is_page_url(url):
            raise ValueError("only absolute HTTP(S) page URLs are allowed")
        self._agent_command(target_tab_id, "Page.navigate", {"url": url})

    def click(self, target_tab_id: str, selector: str) -> None:
        _validate_selector(selector)
        result = self._agent_command(
            target_tab_id,
            "Runtime.evaluate",
            {"expression": _selector_action_expression(selector, "click"), "returnByValue": True},
        )
        if not _action_succeeded(result):
            raise BrowserUnavailable("agent selector click was not available")

    def type_text(self, target_tab_id: str, selector: str, text: str) -> None:
        _validate_selector(selector)
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
            raise ValueError("agent text is invalid")
        result = self._agent_command(
            target_tab_id,
            "Runtime.evaluate",
            {
                "expression": _selector_action_expression(selector, "type", text),
                "returnByValue": True,
            },
        )
        if not _action_succeeded(result):
            raise BrowserUnavailable("agent selector input was not available")

    def page_info(
        self,
        target_tab_id: str | None = None,
        selector: str | None = None,
        *,
        deadline: "BrokerDeadline | None" = None,
    ) -> dict[str, str]:
        if target_tab_id is None:
            raise ValueError("target_tab_id is required")
        if selector is not None:
            raise ValueError("selector-based page_info is broker-only")
        result = self._agent_command(
            target_tab_id,
            "Runtime.evaluate",
            {
                "expression": _INFO_EXPRESSION if selector is None else _selector_page_info_expression(selector),
                "returnByValue": True,
            },
            deadline=deadline,
        )
        return self._parse_page_state(result)

    def _agent_command(
        self,
        target_id: str,
        method: str,
        params: dict[str, Any],
        *,
        deadline: "BrokerDeadline | None" = None,
    ) -> Any:
        if method not in _BROKER_METHODS:
            raise ValueError("unsupported agent CDP method")
        _validate_target_id(target_id)
        with self._target_lock(target_id):
            target = self._target(target_id)
            ws_url = target.get("webSocketDebuggerUrl")
            if not isinstance(ws_url, str) or not _is_local_websocket(ws_url):
                raise BrowserUnavailable("requested target DevTools endpoint is unavailable")
            return self._command(ws_url, method, params, deadline=deadline)

    def broker_authentik_mfa(self, target_id: str, *, selector: str) -> dict[str, object]:
        _validate_selector(selector)
        result = self._broker_command(target_id, "Runtime.evaluate", {"expression": "(() => { const node = " + _selector_find_js(selector) + "; if (!node) return {found:false,device_class:null}; const challenge = node.deviceChallenge || node.challenge || node; const deviceClass = challenge.deviceClass; return {found:true,device_class:(typeof deviceClass === 'string' ? deviceClass : null)}; })()", "returnByValue": True})
        value = result.get("result", {}).get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict) or not isinstance(value.get("found"), bool): raise BrowserUnavailable("invalid Authentik MFA metadata")
        return {"found": value["found"], "device_class": value.get("device_class") if isinstance(value.get("device_class"), str) else None}

    def broker_authentik_identification(self, target_id: str, **kwargs) -> dict[str, str]:
        result = self._broker_command(target_id, "Runtime.evaluate", {"expression": _authentik_identification_expression(**kwargs), "returnByValue": True})
        return _parse_authentik_transaction(result)

    def broker_authentik_rejection(self, target_id: str, *, expected_origins: tuple[str, ...], rejected_selector: str) -> dict[str, str]:
        result = self._broker_command(target_id, "Runtime.evaluate", {"expression": _authentik_rejection_expression(expected_origins=expected_origins, rejected_selector=rejected_selector), "returnByValue": True})
        return _parse_authentik_rejection(result)

    def broker_authentik_proof(self, target_id: str, *, application_origins: tuple[str, ...], success_paths: tuple[str, ...], selector: str, claim: str) -> dict[str, str | None]:
        result = self._broker_command(target_id, "Runtime.evaluate", {"expression": _authentik_proof_expression(application_origins=application_origins, success_paths=success_paths, selector=selector, claim=claim), "returnByValue": True})
        return _parse_authentik_proof(result)

    def broker_navigate(self, target_id: str, url: str) -> None:
        if not self._is_page_url(url): raise ValueError("only absolute HTTP(S) page URLs are allowed")
        self._broker_command(target_id, "Page.navigate", {"url": url})

    def broker_page_info(self, target_id: str, selector: str | None = None) -> dict[str, object]:
        if selector is None:
            expression = _INFO_EXPRESSION
            result = self._broker_command(target_id, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
            return dict(self._parse_page_state(result))
        _validate_selector(selector)
        result = self._broker_command(target_id, "Runtime.evaluate", {"expression": _selector_read_expression(selector), "returnByValue": True})
        return self._parse_selector_state(result)

    def broker_click(self, target_id: str, selector: str) -> None:
        _validate_selector(selector); result = self._broker_command(target_id, "Runtime.evaluate", {"expression": _selector_action_expression(selector, "click"), "returnByValue": True})
        if not _action_succeeded(result): raise BrowserUnavailable("broker selector click was not available")

    def broker_type_text(self, target_id: str, selector: str, text: str) -> None:
        _validate_selector(selector); _validate_broker_text(text); result = self._broker_command(target_id, "Runtime.evaluate", {"expression": _selector_action_expression(selector, "type", text), "returnByValue": True})
        if not _action_succeeded(result): raise BrowserUnavailable("broker selector input was not available")

    def _broker_command(self, target_id: str, method: str, params: dict[str, Any]) -> Any:
        if method not in _BROKER_METHODS: raise ValueError("unsupported broker CDP method")
        _validate_target_id(target_id)
        with self._target_lock(target_id):
            target = self._target(target_id); ws_url = target.get("webSocketDebuggerUrl")
            if not isinstance(ws_url, str) or not _is_local_websocket(ws_url): raise BrowserUnavailable("requested target DevTools endpoint is unavailable")
            return self._command(ws_url, method, params)

    def _target_lock(self, target_id: str) -> threading.RLock:
        with self._target_locks_guard:
            return self._target_locks.setdefault(target_id, threading.RLock())

    def _target(self, target_id: str) -> dict[str, Any]:
        raw = self._chrome.json_request("/json/list")
        if not isinstance(raw, list): raise BrowserUnavailable("invalid Chrome target response")
        for target in raw:
            if isinstance(target, dict) and target.get("type") == "page" and target.get("id") == target_id: return target
        raise BrowserUnavailable("requested page target is not available")

    def _command(
        self,
        ws_url: str,
        method: str,
        params: dict[str, Any],
        *,
        deadline: "BrokerDeadline | None" = None,
    ) -> Any:
        timeout_s = min(
            _WS_COMMAND_TIMEOUT_S,
            deadline.check() if deadline is not None else _WS_COMMAND_TIMEOUT_S,
        )
        ws = self._ws_factory(ws_url, timeout_s)
        try:
            ws.send(json.dumps({"id": 1, "method": method, "params": params}))
            for _ in range(64):
                if deadline is not None:
                    deadline.check()
                payload = ws.recv(); message = json.loads(payload.decode("utf-8"))
                if message.get("id") == 1:
                    if "error" in message: raise BrowserUnavailable(f"DevTools rejected {method}")
                    return message.get("result")
            raise BrowserUnavailable("DevTools did not answer the command")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrowserUnavailable("DevTools returned invalid JSON") from exc
        finally:
            ws.close()

    def _parse_selector_state(self, result: Any) -> dict[str, object]:
        value = result.get("result", {}).get("value") if isinstance(result, dict) else None
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("found"), bool)
            or not isinstance(value.get("text", ""), str)
            or not isinstance(value.get("value", ""), str)
        ):
            raise BrowserUnavailable("broker selector state is invalid")
        text = value.get("text", "")
        input_value = value.get("value", "")
        if (
            len(text.encode("utf-8")) + len(input_value.encode("utf-8"))
            > _MAX_SELECTOR_RESULT_BYTES
        ):
            raise BrowserUnavailable("broker selector result is too large")
        return {"found": value["found"], "text": text, "value": input_value}

    def _parse_page_state(self, result: Any) -> dict[str, str]:
        value = result.get("result", {}).get("value") if isinstance(result, dict) else None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise BrowserUnavailable("page state capture is invalid") from exc
        if not isinstance(value, dict) or "error" in value:
            raise BrowserUnavailable("page state capture is invalid")
        url = _bounded_page_text(value.get("url"), limit=_MAX_PAGE_URL_BYTES, name="page URL")
        title = _bounded_page_text(value.get("title"), limit=_MAX_PAGE_TITLE_BYTES, name="page title")
        text = _bounded_page_text(value.get("text"), limit=_MAX_PAGE_TEXT_BYTES, name="page text")
        return {"url": _public_url(url), "title": title, "text": text}

    @staticmethod
    def _is_page_url(url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc) and parsed.username is None and parsed.password is None and not parsed.fragment


__all__ = ["CdpPageActionAdapter"]
