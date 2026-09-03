"""Test seams for CloudFiles ingest and internal downloads integration."""

from .browser_downloads import (
    BrowserDownloadCompleted,
    FakeBrowserDownloadSource,
    connect_browser_downloads,
)
from .downloads_adapter import DownloadsStoreAdapter
from .downloads_client import (
    DownloadsClient,
    DownloadsClientError,
    DownloadsHttpError,
    DownloadsTimeout,
)
from .ingest import (
    DownloadsPort,
    IngestPipeline,
    IngestReceipt,
    IngestReceiptError,
    Scanner,
    bounded_copy,
)
from .scanner import CleanScanner

__all__ = [
    "BrowserDownloadCompleted",
    "CleanScanner",
    "DownloadsClient",
    "DownloadsClientError",
    "DownloadsHttpError",
    "DownloadsPort",
    "DownloadsStoreAdapter",
    "DownloadsTimeout",
    "FakeBrowserDownloadSource",
    "IngestPipeline",
    "IngestReceipt",
    "IngestReceiptError",
    "Scanner",
    "bounded_copy",
    "connect_browser_downloads",
]
