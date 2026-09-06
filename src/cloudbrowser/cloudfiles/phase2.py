"""Test seams for CloudFiles ingest and internal downloads integration."""

from .browser_downloads import (
    BrowserDownloadCompleted,
    BrowserDownloadWatcher,
    DownloadWatchConfig,
    FakeBrowserDownloadSource,
    completed_downloads,
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
from .ingest_api import create_ingest_server
from .ingest_client import (
    IngestClient,
    IngestClientError,
    IngestHttpError,
    IngestTimeout,
)
from .scanner import CleanScanner

__all__ = [
    "BrowserDownloadCompleted",
    "BrowserDownloadWatcher",
    "CleanScanner",
    "DownloadWatchConfig",
    "DownloadsClient",
    "DownloadsClientError",
    "DownloadsHttpError",
    "DownloadsPort",
    "DownloadsStoreAdapter",
    "DownloadsTimeout",
    "FakeBrowserDownloadSource",
    "IngestClient",
    "IngestClientError",
    "IngestHttpError",
    "IngestPipeline",
    "IngestReceipt",
    "IngestReceiptError",
    "IngestTimeout",
    "Scanner",
    "bounded_copy",
    "completed_downloads",
    "connect_browser_downloads",
    "create_ingest_server",
]
