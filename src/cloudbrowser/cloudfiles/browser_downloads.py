"""Phase 2 local integration of the browser completion seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Callable

from .contracts import PrincipalBinding
from .ingest import IngestPipeline, IngestReceipt


@dataclass(frozen=True)
class BrowserDownloadCompleted:
    """Completion event with a server-derived owner binding."""

    binding: PrincipalBinding
    source_name: str
    source: BinaryIO


class FakeBrowserDownloadSource:
    """Deterministic event source for local integration tests."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[BrowserDownloadCompleted], IngestReceipt]] = []

    def subscribe(self, handler: Callable[[BrowserDownloadCompleted], IngestReceipt]) -> None:
        self._handlers.append(handler)

    def complete(self, event: BrowserDownloadCompleted) -> list[IngestReceipt]:
        return [handler(event) for handler in tuple(self._handlers)]


def connect_browser_downloads(source: FakeBrowserDownloadSource, pipeline: IngestPipeline) -> None:
    """Connect browser completion events to the owner-bound pipeline."""

    def handle(event: BrowserDownloadCompleted) -> IngestReceipt:
        return pipeline.ingest(binding=event.binding, source_name=event.source_name, source=event.source)

    source.subscribe(handle)


__all__ = ["BrowserDownloadCompleted", "FakeBrowserDownloadSource", "connect_browser_downloads"]
