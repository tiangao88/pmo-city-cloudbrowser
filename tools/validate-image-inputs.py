#!/usr/bin/env python3
"""Validate service-image inputs without requiring a local Docker daemon."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("router", "slot-supervisor", "viewer", "downloads", "credential-broker")


def main() -> None:
    for service in SERVICES:
        path = ROOT / "services" / service / "Dockerfile"
        text = path.read_text(encoding="utf-8")
        if not text.startswith("FROM python:3.12-slim\n"):
            raise SystemExit(f"{service}: unsupported base image")
        for marker in (
            "COPY src/ /app/src/",
            f"COPY services/{service}/entrypoint.py",
            "USER cloudbrowser",
            "HEALTHCHECK",
            "ENTRYPOINT",
        ):
            if marker not in text:
                raise SystemExit(f"{service}: missing Dockerfile marker {marker}")
    print("image-input validation: PASS")


if __name__ == "__main__":
    main()
