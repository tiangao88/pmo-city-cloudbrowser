"""Owner-bound, page-state-only agent control for one browser binding."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
from typing import Callable, Mapping
from urllib.parse import urlsplit

from .browser_slots.transport import BrowserReadiness, BrowserUnavailable

_MAX_REQUEST_ID = 128
_MAX_IDENTITY = 256
_MAX_SELECTOR = 512
_MAX_TEXT = 4096
_MAX_URL = 2048
_MAX_TABS = 32
_MAX_BODY = 8192
_MAX_RESPONSE = 64 * 1024

ALLOWED_AGENT_OPERATIONS = frozenset({"navigate", "click", "type", "page_info", "tabs_list"})
FORBIDDEN_AGENT_OPERATIONS = frozenset(
    {
        "raw_cdp",
        "evaluate",
        "cookies",
        "storage",
        "network",
        "filesystem",
        "process",
        "credential_material",
        "password_values",
    }
)
_SENSITIVE_SELECTOR_MARKERS = (
    "password",
    "passwd",
    "passcode",
    "otp",
    "one-time",
    "token",
    "secret",
    "credential",
    "cookie",
    "authorization",
    "auth-header",
)
_SENSITIVE_TEXT_MARKERS = (
    "password=",
    "passwd=",
    "passcode=",
    "otp=",
    "token=",
    "secret=",
    "authorization:",
    "cookie:",
    "set-cookie:",
)


@dataclass(frozen=True)
class PageState:
    """Bounded page state with safe URL and obvious-secret redaction."""

    url: str
    title: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not _safe_observed_url(self.url) or len(self.url) > _MAX_URL:
            raise ValueError("page url is invalid")
        for name in ("title", "text"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > _MAX_TEXT:
                raise ValueError("page state is invalid")
            if _contains_sensitive_marker(value):
                raise ValueError("page state contains blocked sensitive content")

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "title": self.title, "text": self.text}


@dataclass(frozen=True)
class AgentControlRequest:
    """Agent input; server-owned binding fields are checked before dispatch."""

    request_id: str
    principal_id: str
    browser_id: str
    generation: str
    operation: str
    params: Mapping[str, object]


class RestrictedAgentBrowser:
    """Narrow callbacks for page actions; no generic CDP callback is accepted."""

    def __init__(
        self,
        *,
        readiness: Callable[[], BrowserReadiness],
        list_pages: Callable[[], list[dict[str, str]]] | None = None,
        navigate: Callable[[str], None] | None = None,
        click: Callable[[str], None] | None = None,
        type_text: Callable[[str, str], None] | None = None,
        page_info: Callable[[str | None], PageState] | Callable[[], PageState] | None = None,
    ) -> None:
        self._readiness = readiness
        self._list_pages = list_pages
        self._navigate = navigate
        self._click = click
        self._type_text = type_text
        self._page_info = page_info

    def readiness(self) -> BrowserReadiness:
        return self._readiness()

    def list_pages(self) -> list[dict[str, str]]:
        if self._list_pages is None:
            raise BrowserUnavailable("page listing is unavailable")
        pages = self._list_pages()
        if not isinstance(pages, list) or len(pages) > _MAX_TABS:
            raise BrowserUnavailable("page listing is invalid")
        bounded: list[dict[str, str]] = []
        for page in pages:
            if not isinstance(page, dict):
                raise BrowserUnavailable("page listing is invalid")
            tab_id, url, title = page.get("tab_id"), page.get("url"), page.get("title")
            if not all(isinstance(value, str) and value and len(value) <= _MAX_TEXT for value in (tab_id, url, title)):
                raise BrowserUnavailable("page listing is invalid")
            if not _safe_observed_url(url) or _contains_sensitive_marker(title):
                raise BrowserUnavailable("page listing contains blocked content")
            bounded.append({"tab_id": tab_id, "url": url, "title": title})
        return bounded

    def navigate(self, url: str) -> None:
        if self._navigate is None:
            raise BrowserUnavailable("navigation is unavailable")
        self._navigate(url)

    def click(self, selector: str) -> None:
        if self._click is None:
            raise BrowserUnavailable("click is unavailable")
        self._click(selector)

    def type_text(self, selector: str, text: str) -> None:
        if self._type_text is None:
            raise BrowserUnavailable("typing is unavailable")
        self._type_text(selector, text)

    def page_info(self, selector: str | None = None) -> PageState:
        if self._page_info is None:
            raise BrowserUnavailable("page state is unavailable")
        try:
            state = self._page_info(selector)
        except TypeError:
            state = self._page_info()  # type: ignore[call-arg]
        if not isinstance(state, PageState):
            raise BrowserUnavailable("page state is invalid")
        return state


class AgentControlService:
    """Authorize each request to one server-owned browser binding."""

    def __init__(
        self,
        browser: RestrictedAgentBrowser,
        *,
        principal_id: str,
        browser_id: str,
        generation: str,
    ) -> None:
        self._browser = browser
        self._principal_id = _bounded_identity(principal_id, "principal_id")
        self._browser_id = _bounded_identity(browser_id, "browser_id")
        self._generation = _bounded_identity(generation, "generation")

    def handle(self, request: AgentControlRequest) -> dict[str, object]:
        request_id = request.request_id if isinstance(request.request_id, str) else ""
        if not request_id or len(request_id) > _MAX_REQUEST_ID:
            return self._failure(request_id, "invalid_request")
        if (
            request.principal_id != self._principal_id
            or request.browser_id != self._browser_id
            or request.generation != self._generation
        ):
            return self._failure(request_id, "owner_mismatch")
        if request.operation in FORBIDDEN_AGENT_OPERATIONS:
            return {"request_id": request_id, "status": "unsupported", "error_code": "capability_denied"}
        if request.operation not in ALLOWED_AGENT_OPERATIONS:
            return {"request_id": request_id, "status": "unsupported", "error_code": "operation_not_supported"}
        if not isinstance(request.params, Mapping):
            return self._failure(request_id, "invalid_request")
        try:
            ready = self._browser.readiness()
            if not _matches(ready, self._principal_id, self._generation):
                return self._failure(request_id, "owner_mismatch")
            if not ready.cdp_ok:
                return self._failure(request_id, "browser_unavailable")
            result = self._dispatch(request.operation, request.params)
            # Re-check after every action/read to close the owner handoff race.
            final_ready = self._browser.readiness()
            if not _matches(final_ready, self._principal_id, self._generation):
                return self._failure(request_id, "owner_mismatch")
            payload: dict[str, object] = {"request_id": request_id, "status": "ok"}
            if result is not None:
                payload["page"] = result.to_dict() if isinstance(result, PageState) else result
            if len(json.dumps(payload, separators=(",", ":"))) > _MAX_RESPONSE:
                return self._failure(request_id, "response_too_large")
            return payload
        except (ValueError, TypeError):
            return self._failure(request_id, "invalid_request")
        except BrowserUnavailable:
            return self._failure(request_id, "browser_unavailable")
        except Exception:
            return self._failure(request_id, "operation_failed")

    def _dispatch(self, operation: str, params: Mapping[str, object]) -> PageState | list[dict[str, str]] | None:
        if operation == "page_info":
            selector = params.get("selector")
            if selector is not None:
                _require_selector(selector)
            return self._browser.page_info(selector if isinstance(selector, str) else None)
        if operation == "tabs_list":
            return self._browser.list_pages()
        if operation == "navigate":
            url = params.get("url")
            if not isinstance(url, str) or not _safe_navigation_url(url):
                raise ValueError("url is invalid")
            self._browser.navigate(url)
            return None
        if operation == "click":
            selector = _require_selector(params.get("selector"))
            self._browser.click(selector)
            return None
        if operation == "type":
            selector = _require_selector(params.get("selector"))
            if _is_sensitive_selector(selector):
                raise ValueError("sensitive input is broker-only")
            text = params.get("text")
            if not isinstance(text, str) or not text or len(text) > _MAX_TEXT or _contains_sensitive_marker(text):
                raise ValueError("text is invalid")
            self._browser.type_text(selector, text)
            return None
        raise ValueError("unsupported operation")

    @staticmethod
    def _failure(request_id: str, error_code: str) -> dict[str, object]:
        return {"request_id": request_id, "status": "failed", "error_code": error_code}

    @classmethod
    def create_server(
        cls,
        browser: RestrictedAgentBrowser,
        *,
        principal_id: str,
        browser_id: str,
        generation: str,
        shared_secret: str | None = None,
        address: tuple[str, int] = ("127.0.0.1", 8090),
    ) -> ThreadingHTTPServer:
        """Create POST /agent-control/v1 and GET /health."""
        service = cls(browser, principal_id=principal_id, browser_id=browser_id, generation=generation)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
                if self.path != "/health":
                    self.send_error(404)
                    return
                self._send_json(200, {"status": "ok", "component": "agent-control"})

            def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
                if self.path != "/agent-control/v1":
                    self.send_error(404)
                    return
                if shared_secret is None or not hmac.compare_digest(
                    self.headers.get("X-CB-Trusted-Secret", ""), shared_secret
                ):
                    self._send_json(401, {"status": "failed", "error_code": "unauthorized"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > _MAX_BODY:
                        raise ValueError
                    raw = json.loads(self.rfile.read(length))
                    if not isinstance(raw, dict):
                        raise ValueError
                    if any(key not in raw for key in ("request_id", "operation", "params")):
                        raise ValueError
                    request = AgentControlRequest(
                        request_id=raw["request_id"],
                        principal_id=principal_id,
                        browser_id=browser_id,
                        generation=generation,
                        operation=raw["operation"],
                        params=raw["params"],
                    )
                    result = service.handle(request)
                except (ValueError, TypeError, json.JSONDecodeError):
                    result = {"request_id": "", "status": "failed", "error_code": "invalid_request"}
                self._send_json(200, result)

            def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        return ThreadingHTTPServer(address, Handler)


def _bounded_identity(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTITY:
        raise ValueError(f"{name} is invalid")
    return value


def _matches(readiness: BrowserReadiness, principal_id: str, generation: str) -> bool:
    return isinstance(readiness, BrowserReadiness) and readiness.owner == principal_id and readiness.generation == generation


def _require_selector(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_SELECTOR:
        raise ValueError("selector is invalid")
    return value


def _is_sensitive_selector(selector: str) -> bool:
    lowered = selector.lower()
    return any(marker in lowered for marker in _SENSITIVE_SELECTOR_MARKERS)


def _contains_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SENSITIVE_TEXT_MARKERS)


def _safe_navigation_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        isinstance(url, str)
        and len(url) <= _MAX_URL
        and parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and ".." not in parsed.path
        and not parsed.fragment
    )


def _safe_observed_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        _safe_navigation_url(url)
        and not parsed.query
    )


__all__ = [
    "ALLOWED_AGENT_OPERATIONS",
    "AgentControlRequest",
    "AgentControlService",
    "FORBIDDEN_AGENT_OPERATIONS",
    "PageState",
    "RestrictedAgentBrowser",
]
