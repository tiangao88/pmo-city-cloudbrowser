"""Narrow browser transport contract for slot-supervisor orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BrowserUnavailable(RuntimeError):
    """Raised when the browser transport cannot be reached or operated."""


class BrowserOwnershipChanged(RuntimeError):
    """Raised when the transport reports a different owner generation."""


@dataclass(frozen=True)
class BrowserReadiness:
    """Non-sensitive readiness observation from the browser transport."""

    owner: str
    generation: str
    cdp_ok: bool


class BrowserTransport(Protocol):
    """Minimal supervisor-owned browser operations; no raw CDP is exposed."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def readiness(self) -> BrowserReadiness: ...

    def list_page_urls(self) -> list[str]: ...

    def open_page(self, url: str) -> None: ...

    def close_empty_pages(self) -> None: ...
