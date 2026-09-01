#!/usr/bin/env python3
"""Run an HTTP health check against one explicitly selected instance."""

from argparse import ArgumentParser
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cloudbrowser.deployment import InstanceNamespace  # noqa: E402


if __name__ == "__main__":
    cli = ArgumentParser(description=__doc__)
    cli.add_argument("--instance-id", required=True)
    cli.add_argument("--url", required=True)
    args = cli.parse_args()
    namespace = InstanceNamespace(args.instance_id)
    request = urllib.request.Request(args.url, headers={"X-CloudBrowser-Instance": namespace.instance_id})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"health check failed for {namespace.instance_id}") from exc
    if not isinstance(payload, dict) or payload.get("instance_id") != namespace.instance_id:
        raise SystemExit("health response is not scoped to --instance-id")
    print("health check: PASS")
