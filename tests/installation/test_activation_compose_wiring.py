"""Activation-driven slot compose contract (boot-stopped browser).

Session activation boots the browser STOPPED (``CB_BROWSER_AUTOSTART=0``)
and the router mints per-slot browser IDs (``browser-{slot_id}``, i.e.
``browser-slot-1``). Both compose variants must therefore:

- boot the browser stopped and give it the placeholder binding whose
  ``browser_id`` matches the router's minting rule for slot-1;
- give the slot supervisor the same matching ``browser_id`` placeholder;
- wire ``CB_ROUTER_SHARED_SECRET`` into the browser so trusted binding
  pushes are accepted;
- drop static per-slot binding env from agent-control (its lease rotates
  via ``POST /agent-control/lease`` instead).

Static ``browser-dev01``/``principal-dev01``/``generation-dev01-g1``
placeholders would make every wake fail with ``slot_mismatch``.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = ROOT / "deploy" / "coolify"
FILES = ("compose.yaml", "compose.coolify.yaml")


def _service_block(filename: str, service: str) -> str:
    compose = (COMPOSE_DIR / filename).read_text(encoding="utf-8")
    lines = compose.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.rstrip() == f"  {service}:":
            start = index
            break
    if start is None:
        raise AssertionError(f"{service} block missing from {filename}")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith("    ") and not line.startswith("      ") and line.strip() and not line.lstrip().startswith("#"):
            break
        block.append(line)
    return "\n".join(block)


def test_browser_boots_stopped_with_matching_placeholder() -> None:
    for filename in FILES:
        block = _service_block(filename, "browser")
        assert "CB_BROWSER_AUTOSTART: ${CB_BROWSER_AUTOSTART:-0}" in block, filename
        # The placeholder browser_id must match the router minting rule
        # browser-{slot_id} for slot-1.
        assert "CB_BROWSER_ID: ${CB_BROWSER_ID:-browser-slot-1}" in block, filename
        assert (
            "CB_PRINCIPAL_ID: ${CB_PRINCIPAL_ID:-principal-unassigned}" in block
        ), filename
        assert (
            "CB_BINDING_GENERATION: ${CB_BINDING_GENERATION:-generation-0}" in block
        ), filename


def test_browser_carries_router_trusted_secret_for_binding_pushes() -> None:
    for filename in FILES:
        block = _service_block(filename, "browser")
        assert "CB_ROUTER_SHARED_SECRET:" in block, filename


def test_slot_supervisor_placeholder_matches_router_minting() -> None:
    for filename in FILES:
        block = _service_block(filename, "slot-supervisor")
        assert "CB_BROWSER_ID: ${CB_BROWSER_ID:-browser-slot-1}" in block, filename
        assert (
            "CB_PRINCIPAL_ID: ${CB_PRINCIPAL_ID:-principal-unassigned}" in block
        ), filename
        assert (
            "CB_BINDING_GENERATION: ${CB_BINDING_GENERATION:-generation-0}" in block
        ), filename


def test_agent_control_does_not_pin_static_slot_binding() -> None:
    for filename in FILES:
        block = _service_block(filename, "agent-control")
        assert "CB_BROWSER_ID" not in block, filename
        assert "CB_PRINCIPAL_ID" not in block, filename
        assert "CB_BINDING_GENERATION" not in block, filename
