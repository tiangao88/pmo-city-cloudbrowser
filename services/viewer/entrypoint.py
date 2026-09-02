"""Viewer service bootstrap with authenticated, server-derived binding."""

from __future__ import annotations

import os
import time

from cloudbrowser.service_runtime import run_service


if __name__ == "__main__":
    run_service("viewer")
