"""Bounded CDP page actions for the deployed browser slot.

Decision 2026-09-08 (Tigo): milestone acceptance needs ``navigate`` and
``page_info`` working end-to-end. The adapter speaks only to the local,
service-owned Chrome DevTools endpoint:

- Target discovery and creation go through the same HTTP JSON API the
  supervisor already uses (``/json/list``, ``/json/new``).
- One command at a time is sent over a short-lived WebSocket to the page
  target (``Page.navigate`` for navigation, ``Runtime.evaluate`` for the
  bounded page-state capture).
- ``click``/``type_text`` intentionally remain fail-closed: no untrusted
  element-interaction channel is approved yet.
- No generic CDP passthrough is exposed; payloads are bounded and
  validated. Callers re-validate captured state (``agent_control``'s
  ``PageState`` redaction applies upstream).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from .transport import BrowserUnavailable

_MAX_TEXT_BYTES = 64 * 1024
_WS_OPEN_TIMEOUT_S = 3.0
_WS_COMMAND_TIMEOUT_S = 5.0
_WS_RECV_CHUNK = 64 * 1024
_INFO_EXPRESSION = (
    "JSON.stringify({"
    "url: location.href, "
    "title: document.title, "
    "text: (document.body ? document.body.innerText : '').slice(0, 4096)"
    "})"
)


class _WebSocket:
    """Minimal RFC 6455 client for one CDP command-response exchange."""

    def __init__(self, url: str, *, open_timeout_s: float, command_timeout_s: float) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise BrowserUnavailable("DevTools WebSocket must be local")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        try:
            self._sock = socket.create_connection((parsed.hostname, port), timeout=open_timeout_s)
        except OSError as exc:
            raise BrowserUnavailable("DevTools WebSocket is unavailable") from exc
        self._sock.settimeout(command_timeout_s)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {parsed.path}?{parsed.query} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        try:
            self._sock.sendall(handshake)
            status_line, headers = self._read_http_response()
            if status_line.split(" ", 2)[1:2] != ["101"]:
                raise BrowserUnavailable("DevTools WebSocket handshake refused")
            if headers.get("upgrade", "").lower() != "websocket":
                raise BrowserUnavailable("DevTools WebSocket upgrade failed")
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
        header = bytearray([0x81])  # FIN + text frame, client frames are masked
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        try:
            self._sock.sendall(bytes(header) + masked)
        except OSError as exc:
            raise BrowserUnavailable("DevTools WebSocket send failed") from exc

    def recv(self, _size: int = _WS_RECV_CHUNK) -> bytes:
        try:
            while True:
                header = self._read_exact(2)
                opcode = header[0] & 0x0F
                length = header[1] & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._read_exact(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._read_exact(8))[0]
                payload = self._read_exact(length) if length else b""
                if opcode == 0x8:  # close
                    raise BrowserUnavailable("DevTools WebSocket closed early")
                if opcode == 0x9:  # ping -> pong and continue
                    self._send_pong(payload)
                    continue
                if opcode in (0x1, 0x2):
                    return payload
        except BrowserUnavailable:
            raise
        except (OSError, struct.error) as exc:
            raise BrowserUnavailable("DevTools WebSocket receive failed") from exc

    def _send_pong(self, payload: bytes) -> None:
        frame = bytearray([0x8A])
        length = len(payload)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame += struct.pack(">H", length)
        else:
            frame.append(0x80 | 127)
            frame += struct.pack(">Q", length)
        mask = os.urandom(4)
        frame += mask
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
        sock = getattr(self, "_sock", None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


class CdpPageActionAdapter:
    """Concrete ``PageActionAdapter`` backed by the local DevTools endpoint."""

    def __init__(
        self,
        chrome: Any,
        *,
        ws_factory: Callable[[str, float], Any] | None = None,
        max_text_bytes: int = _MAX_TEXT_BYTES,
    ) -> None:
        self._chrome = chrome
        self._ws_factory = ws_factory or (
            lambda url, timeout_s: _WebSocket(
                url, open_timeout_s=_WS_OPEN_TIMEOUT_S, command_timeout_s=timeout_s
            )
        )
        if max_text_bytes <= 0:
            raise ValueError("max_text_bytes must be positive")
        self._max_text_bytes = max_text_bytes

    def navigate(self, url: str) -> None:
        if not self._is_page_url(url):
            raise ValueError("only absolute HTTP(S) page URLs are allowed")
        target_ws = self._first_page_websocket()
        if target_ws is not None:
            self._command(target_ws, "Page.navigate", {"url": url})
            return
        self._chrome.json_request("/json/new?" + quote(url, safe=""), method="PUT")

    def click(self, selector: str) -> None:
        raise BrowserUnavailable("click is not available in this release")

    def type_text(self, selector: str, text: str) -> None:
        raise BrowserUnavailable("typing is not available in this release")

    def page_info(self, selector: str | None = None) -> dict[str, str]:
        if selector:
            # Selector-bearing lookups need a bounded request shape that the
            # internal HTTP client cannot carry yet; refuse loudly instead
            # of silently ignoring the argument.
            raise ValueError("selector-based page_info is not supported")
        target_ws = self._first_page_websocket()
        if target_ws is None:
            raise BrowserUnavailable("no page target is available")
        result = self._command(target_ws, "Runtime.evaluate", {
            "expression": _INFO_EXPRESSION,
            "returnByValue": True,
        })
        return self._parse_page_state(result)

    def _first_page_websocket(self) -> str | None:
        raw = self._chrome.json_request("/json/list")
        if not isinstance(raw, list):
            raise BrowserUnavailable("invalid Chrome target response")
        for target in raw:
            if not isinstance(target, dict) or target.get("type") != "page":
                continue
            ws_url = target.get("webSocketDebuggerUrl")
            if isinstance(ws_url, str) and ws_url.startswith("ws://"):
                return ws_url
        return None

    def _command(self, ws_url: str, method: str, params: dict[str, Any]) -> Any:
        ws = self._ws_factory(ws_url, _WS_COMMAND_TIMEOUT_S)
        try:
            ws.send(json.dumps({"id": 1, "method": method, "params": params}))
            deadline_replies = 0
            while deadline_replies < 64:  # bounded event drain between commands
                payload = ws.recv()
                try:
                    message = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BrowserUnavailable("DevTools returned invalid JSON") from exc
                if message.get("id") == 1:
                    if "error" in message:
                        raise BrowserUnavailable(f"DevTools rejected {method}")
                    return message.get("result")
                deadline_replies += 1
            raise BrowserUnavailable("DevTools did not answer the command")
        finally:
            ws.close()

    def _parse_page_state(self, result: Any) -> dict[str, str]:
        value = result.get("result", {}).get("value") if isinstance(result, dict) else None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = None
        if not isinstance(value, dict):
            raise BrowserUnavailable("page state capture is invalid")
        url, title, text = value.get("url"), value.get("title"), value.get("text")
        if not all(isinstance(item, str) for item in (url, title, text)):
            raise BrowserUnavailable("page state capture is invalid")
        assert isinstance(url, str) and isinstance(title, str) and isinstance(text, str)
        if len(title) + len(text) > self._max_text_bytes:
            raise BrowserUnavailable("page state capture is too large")
        return {"url": url, "title": title, "text": text}

    @staticmethod
    def _is_page_url(url: str) -> bool:
        parsed = urlsplit(url)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )


__all__ = ["CdpPageActionAdapter"]
