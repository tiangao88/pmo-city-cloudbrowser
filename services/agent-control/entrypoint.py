"""Minimal agent-control HTTP service entrypoint."""

from cloudbrowser.service_runtime import run_service


if __name__ == "__main__":
    run_service("agent-control")
