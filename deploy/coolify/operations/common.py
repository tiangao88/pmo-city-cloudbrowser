"""Shared immutable installation backup helpers."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cloudbrowser.deployment import InstanceNamespace  # noqa: E402


def parser(description: str | None) -> ArgumentParser:
    result = ArgumentParser(description=description)
    result.add_argument("--instance-id", required=True)
    result.add_argument("--source", type=Path, required=True)
    result.add_argument("--destination", type=Path, required=True)
    return result


def scoped_paths(args: Namespace) -> tuple[Path, Path]:
    namespace = InstanceNamespace(args.instance_id)
    source = args.source.resolve()
    destination = args.destination.resolve()
    prefix = namespace.instance_id + "-"
    if not destination.name.startswith(prefix):
        raise SystemExit("destination must be scoped to --instance-id")
    if source == destination:
        raise SystemExit("source and destination must differ")
    return source, destination


def copy_tree(args: Namespace) -> None:
    source, destination = scoped_paths(args)
    if not source.exists():
        raise SystemExit("source does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)
