"""Hermes stdio MCP bridge for the bounded CloudBrowser employee surface.

The bridge is intentionally a client of the authenticated viewer routes.  It
does not connect to CDP, accept owner fields, or hold application credentials.
Edge authentication material is injected into this subprocess by the Hermes
profile secret scope and is used only as an outbound HTTP header.
"""

from __future__ import annotations

from http.client import HTTPResponse
import json
import os
import secrets
import sys
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_PROTOCOL_VERSION = "2025-06-18"
_MAX_RPC_LINE_BYTES = 64 * 1024
_MAX_HTTP_BODY_BYTES = 64 * 1024
_MAX_AUTH_BYTES = 4096


class _NoRedirects(HTTPRedirectHandler):
    """Keep profile authentication on the configured CloudBrowser origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _bounded_auth(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not (value.startswith("${") and value.endswith("}"))
        and len(value.encode("utf-8")) <= _MAX_AUTH_BYTES
        and all(ord(char) >= 0x20 and ord(char) != 0x7F for char in value)
    )


def _base_origin(value: str) -> str:
    parsed = urlsplit(value)
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme not in ({"http", "https"} if loopback else {"https"}):
        raise ValueError("CloudBrowser URL must use HTTPS")
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ValueError("CloudBrowser URL must be an origin without userinfo")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("CloudBrowser URL must not include a path, query, or fragment")
    return f"{parsed.scheme}://{parsed.netloc}"


class CloudBrowserHttpClient:
    """Fail-closed HTTP client for the authenticated CloudBrowser viewer API."""

    def __init__(
        self,
        *,
        base_url: str,
        authorization: str = "",
        cookie: str = "",
        timeout_s: float = 15.0,
        request_id_factory: Callable[[], str] | None = None,
        opener=None,
    ) -> None:
        self._origin = _base_origin(base_url)
        if bool(authorization) == bool(cookie):
            raise ValueError("exactly one CloudBrowser authentication channel is required")
        selected = authorization or cookie
        if not _bounded_auth(selected):
            raise ValueError("CloudBrowser authentication is invalid")
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool):
            raise ValueError("timeout must be a number")
        if timeout_s <= 0 or timeout_s > 30:
            raise ValueError("timeout must be positive and at most 30 seconds")
        self._authorization = authorization
        self._cookie = cookie
        self._timeout_s = float(timeout_s)
        self._request_id_factory = request_id_factory or (
            lambda: "mcp-" + secrets.token_urlsafe(12)
        )
        self._opener = opener or build_opener(_NoRedirects())

    def __repr__(self) -> str:
        channel = "authorization" if self._authorization else "cookie"
        return f"CloudBrowserHttpClient(origin={self._origin!r}, auth_channel={channel!r})"

    def start(self) -> dict[str, object]:
        joined = self._post("/ui/session/join", {})
        if joined.get("status") == "offered":
            return self._post("/ui/session/activate", {})
        return joined

    def agent(self, operation: str, params: Mapping[str, object]) -> dict[str, object]:
        return self._post(f"/ui/agent/{operation}", {"params": dict(params)})

    def credential_login(self, *, site_id: str, target_tab_id: str) -> dict[str, object]:
        request_id = self._request_id()
        return self._post(
            "/ui/credential/login",
            {
                "request_id": request_id,
                "site_id": site_id,
                "target_tab_id": target_tab_id,
            },
            request_id=request_id,
        )

    def _request_id(self) -> str:
        value = self._request_id_factory()
        if (
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > 128
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
        ):
            raise RuntimeError("request id generation failed")
        return value

    def _post(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        request_id: str | None = None,
    ) -> dict[str, object]:
        outbound_id = request_id or self._request_id()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-CB-Request-Id": outbound_id,
        }
        if self._authorization:
            headers["Authorization"] = self._authorization
        else:
            headers["Cookie"] = self._cookie
        encoded = json.dumps(dict(body), separators=(",", ":")).encode("utf-8")
        request = Request(
            self._origin + path,
            data=encoded,
            method="POST",
            headers=headers,
        )
        try:
            response: HTTPResponse = self._opener.open(request, timeout=self._timeout_s)
            with response:
                if response.status != 200:
                    return self._http_failure(response.status)
                content_type = response.headers.get_content_type()
                if content_type != "application/json":
                    return {"status": "failed", "error_code": "invalid_response"}
                raw = response.read(_MAX_HTTP_BODY_BYTES + 1)
        except HTTPError as exc:
            return self._http_failure(exc.code)
        except (URLError, TimeoutError, OSError):
            return {"status": "failed", "error_code": "service_unavailable"}
        if len(raw) > _MAX_HTTP_BODY_BYTES:
            return {"status": "failed", "error_code": "invalid_response"}
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"status": "failed", "error_code": "invalid_response"}
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            return {"status": "failed", "error_code": "invalid_response"}
        return payload

    @staticmethod
    def _http_failure(status: int) -> dict[str, object]:
        if status in {301, 302, 303, 307, 308, 401, 403}:
            return {"status": "failed", "error_code": "unauthorized"}
        return {"status": "failed", "error_code": "service_unavailable"}


def _object_schema(properties: Mapping[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": dict(properties),
        "required": required,
    }


_TEXT = {"type": "string", "minLength": 1}
_TOOLS: tuple[dict[str, object], ...] = (
    {
        "name": "cloudbrowser_start",
        "description": "Join and, when offered, activate the current user's CloudBrowser session.",
        "inputSchema": _object_schema({}, []),
    },
    {
        "name": "cloudbrowser_tabs_list",
        "description": "List bounded public metadata for the current user's browser tabs.",
        "inputSchema": _object_schema({}, []),
    },
    {
        "name": "cloudbrowser_tab_open",
        "description": "Open one HTTP(S) page and return Chromium's exact new target ID.",
        "inputSchema": _object_schema({"url": {**_TEXT, "maxLength": 2048}}, ["url"]),
    },
    {
        "name": "cloudbrowser_navigate",
        "description": "Navigate one exact tab to an allowed HTTP(S) URL.",
        "inputSchema": _object_schema(
            {
                "target_tab_id": {**_TEXT, "maxLength": 256},
                "url": {**_TEXT, "maxLength": 2048},
            },
            ["target_tab_id", "url"],
        ),
    },
    {
        "name": "cloudbrowser_click",
        "description": "Click a bounded selector in one exact tab.",
        "inputSchema": _object_schema(
            {
                "target_tab_id": {**_TEXT, "maxLength": 256},
                "selector": {**_TEXT, "maxLength": 512},
            },
            ["target_tab_id", "selector"],
        ),
    },
    {
        "name": "cloudbrowser_type",
        "description": "Type ordinary non-secret text into a bounded selector in one exact tab.",
        "inputSchema": _object_schema(
            {
                "target_tab_id": {**_TEXT, "maxLength": 256},
                "selector": {**_TEXT, "maxLength": 512},
                "text": {"type": "string", "maxLength": 4096},
            },
            ["target_tab_id", "selector", "text"],
        ),
    },
    {
        "name": "cloudbrowser_page_info",
        "description": "Read bounded text-first state from one exact tab.",
        "inputSchema": _object_schema(
            {"target_tab_id": {**_TEXT, "maxLength": 256}}, ["target_tab_id"]
        ),
    },
    {
        "name": "cloudbrowser_credential_login",
        "description": (
            "Request a deterministic login for a declared site and exact tab; "
            "returns status only and never credentials."
        ),
        "inputSchema": _object_schema(
            {
                "site_id": {**_TEXT, "maxLength": 256},
                "target_tab_id": {**_TEXT, "maxLength": 256},
            },
            ["site_id", "target_tab_id"],
        ),
    },
)


def _bounded_string(value: object, *, limit: int, allow_controls: bool = False) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ValueError("invalid tool arguments")
    if not allow_controls and (
        not value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError("invalid tool arguments")
    if allow_controls and any(char == "\x00" for char in value):
        raise ValueError("invalid tool arguments")
    return value


def _safe_url(value: object) -> str:
    url = _bounded_string(value, limit=2048)
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or ".." in parsed.path.split("/")
    ):
        raise ValueError("invalid tool arguments")
    return url


def _exact_arguments(value: object, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid tool arguments")
    return value


class HermesMcpServer:
    """Small dependency-free MCP server that exposes the bounded viewer client."""

    def __init__(self, *, client: CloudBrowserHttpClient | None) -> None:
        self._client = client

    def handle_rpc(self, request: object) -> dict[str, object] | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return self._rpc_error(None, -32600, "Invalid Request")
        method = request.get("method")
        rpc_id = request.get("id")
        if not isinstance(method, str):
            return self._rpc_error(rpc_id, -32600, "Invalid Request")
        if "id" not in request:
            return None
        if isinstance(rpc_id, bool) or not isinstance(rpc_id, (str, int)):
            return self._rpc_error(None, -32600, "Invalid Request")
        params = request.get("params", {})
        if method == "initialize":
            return self._rpc_result(
                rpc_id,
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "pmo-city-cloudbrowser", "version": "0.1.0.dev1"},
                    "instructions": (
                        "Use exact tab IDs. Type only ordinary non-secret text. "
                        "Use cloudbrowser_credential_login for authorized credentials."
                    ),
                },
            )
        if method == "ping":
            return self._rpc_result(rpc_id, {})
        if method == "tools/list":
            return self._rpc_result(rpc_id, {"tools": [dict(tool) for tool in _TOOLS]})
        if method != "tools/call":
            return self._rpc_error(rpc_id, -32601, "Method not found")
        if not isinstance(params, dict) or set(params) - {"name", "arguments", "_meta"}:
            return self._rpc_result(rpc_id, self._tool_failure("invalid_request"))
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str):
            return self._rpc_result(rpc_id, self._tool_failure("invalid_request"))
        try:
            payload = self._call_tool(name, arguments)
        except ValueError:
            return self._rpc_result(rpc_id, self._tool_failure("invalid_request"))
        except Exception:
            return self._rpc_result(rpc_id, self._tool_failure("service_unavailable"))
        failed = payload.get("status") == "failed"
        return self._rpc_result(
            rpc_id,
            self._tool_response(payload, is_error=failed),
        )

    def _call_tool(self, name: str, arguments: object) -> dict[str, object]:
        if self._client is None:
            return {"status": "failed", "error_code": "service_unavailable"}
        if name == "cloudbrowser_start":
            _exact_arguments(arguments, frozenset())
            return self._client.start()
        if name == "cloudbrowser_tabs_list":
            _exact_arguments(arguments, frozenset())
            return self._client.agent("tabs_list", {})
        if name == "cloudbrowser_tab_open":
            args = _exact_arguments(arguments, frozenset({"url"}))
            return self._client.agent("tab_open", {"url": _safe_url(args["url"])})
        if name == "cloudbrowser_navigate":
            args = _exact_arguments(arguments, frozenset({"target_tab_id", "url"}))
            return self._client.agent(
                "navigate",
                {
                    "target_tab_id": _bounded_string(args["target_tab_id"], limit=256),
                    "url": _safe_url(args["url"]),
                },
            )
        if name in {"cloudbrowser_click", "cloudbrowser_type"}:
            fields = {"target_tab_id", "selector"}
            if name == "cloudbrowser_type":
                fields.add("text")
            args = _exact_arguments(arguments, frozenset(fields))
            params: dict[str, object] = {
                "target_tab_id": _bounded_string(args["target_tab_id"], limit=256),
                "selector": _bounded_string(args["selector"], limit=512),
            }
            if name == "cloudbrowser_type":
                params["text"] = _bounded_string(
                    args["text"], limit=4096, allow_controls=True
                )
            return self._client.agent(name.removeprefix("cloudbrowser_"), params)
        if name == "cloudbrowser_page_info":
            args = _exact_arguments(arguments, frozenset({"target_tab_id"}))
            return self._client.agent(
                "page_info",
                {"target_tab_id": _bounded_string(args["target_tab_id"], limit=256)},
            )
        if name == "cloudbrowser_credential_login":
            args = _exact_arguments(arguments, frozenset({"site_id", "target_tab_id"}))
            return self._client.credential_login(
                site_id=_bounded_string(args["site_id"], limit=256),
                target_tab_id=_bounded_string(args["target_tab_id"], limit=256),
            )
        raise ValueError("unsupported tool")

    @staticmethod
    def _tool_response(payload: Mapping[str, object], *, is_error: bool) -> dict[str, object]:
        safe = dict(payload)
        return {
            "content": [
                {"type": "text", "text": json.dumps(safe, separators=(",", ":"))}
            ],
            "structuredContent": safe,
            "isError": is_error,
        }

    @classmethod
    def _tool_failure(cls, error_code: str) -> dict[str, object]:
        return cls._tool_response(
            {"status": "failed", "error_code": error_code}, is_error=True
        )

    @staticmethod
    def _rpc_result(rpc_id: str | int, result: Mapping[str, object]) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": dict(result)}

    @staticmethod
    def _rpc_error(rpc_id: object, code: int, message: str) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": code, "message": message},
        }


def _write_rpc(output, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    output.write(encoded + b"\n")
    output.flush()


def serve_stdio(server: HermesMcpServer, *, input_stream=None, output_stream=None) -> None:
    """Serve newline-delimited JSON-RPC without ever writing diagnostics to stdout."""
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout.buffer
    while True:
        line = input_stream.readline(_MAX_RPC_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > _MAX_RPC_LINE_BYTES and not line.endswith(b"\n"):
            while line and not line.endswith(b"\n"):
                line = input_stream.readline(_MAX_RPC_LINE_BYTES + 1)
            _write_rpc(output_stream, HermesMcpServer._rpc_error(None, -32700, "Parse error"))
            continue
        try:
            request = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            _write_rpc(output_stream, HermesMcpServer._rpc_error(None, -32700, "Parse error"))
            continue
        response = server.handle_rpc(request)
        if response is not None:
            _write_rpc(output_stream, response)


def _client_from_environment(environ: Mapping[str, str]) -> CloudBrowserHttpClient:
    raw_timeout = environ.get("CB_CLOUDBROWSER_TIMEOUT_S", "15")
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("CB_CLOUDBROWSER_TIMEOUT_S is invalid") from exc
    return CloudBrowserHttpClient(
        base_url=environ.get("CB_CLOUDBROWSER_URL", ""),
        authorization=environ.get("CB_CLOUDBROWSER_AUTHORIZATION", ""),
        cookie=environ.get("CB_CLOUDBROWSER_COOKIE", ""),
        timeout_s=timeout,
    )


def main() -> int:
    try:
        client = _client_from_environment(os.environ)
    except ValueError:
        print("CloudBrowser MCP configuration is invalid", file=sys.stderr)
        return 2
    serve_stdio(HermesMcpServer(client=client))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CloudBrowserHttpClient",
    "HermesMcpServer",
    "main",
    "serve_stdio",
]
