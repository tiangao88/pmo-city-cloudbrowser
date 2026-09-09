"""FormLoginBrowser — narrow FormBrowser protocol over the agent sidecar.

Adapts ``HttpAgentBrowser`` (readiness / pages / navigate / click /
type_text / page_info) to the exact ``FormBrowser`` protocol the
``FormLoginAdapter`` needs:

- ``current_url()`` → page_info()["url"]
- ``fill(selector, value)`` → type_text(selector, value)
- ``click(selector)`` → click(selector)
- ``has_selector(selector)`` → page_info(selector)["text"] is non-empty
  (sidecar returns the element's text; a miss returns empty text)
- ``read_text(selector)`` → page_info(selector)["text"]

The adapter receives ONLY this object — never the underlying
``HttpAgentBrowser``, so it cannot navigate, list pages, or read other
tabs. That is the whole point of the narrow protocol (spec 95: adapter
can't exfiltrate or wander).
"""

from __future__ import annotations

from typing import Protocol

from .agent_browser_http import HttpAgentBrowser
from .credential_broker.adapters.form import FormBrowser


class SidecarFormBrowser(FormBrowser):
    """FormBrowser over the agent sidecar; navigate/pages are not exposed."""

    def __init__(self, browser: HttpAgentBrowser) -> None:
        self._browser = browser

    def current_url(self) -> str:
        return self._browser.page_info()["url"]

    def fill(self, selector: str, value: str) -> None:
        self._browser.type_text(selector, value)

    def click(self, selector: str) -> None:
        self._browser.click(selector)

    def has_selector(self, selector: str) -> bool:
        return bool(self._browser.page_info(selector)["text"])

    def read_text(self, selector: str) -> str:
        return self._browser.page_info(selector)["text"]


__all__ = ["SidecarFormBrowser"]
