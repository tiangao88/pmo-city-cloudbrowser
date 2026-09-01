#!/usr/bin/env python3
"""Contract test for durable owner archives across cb-fleet-v2 recreate."""
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "specs" / "26-s7-fleet-compose-v2.yaml"


def service_section(text, name):
    lines = text.splitlines()
    start = lines.index(f"  {name}:")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("  ") and not line.startswith("    "):
            end = i
            break
    return "\n".join(lines[start:end])


def main():
    text = COMPOSE.read_text(encoding="utf-8")
    for slot in ("slot-1", "slot-2"):
        section = service_section(text, slot)
        assert "sessions:/data/sessions" in section, f"{slot}: missing durable archive mount"
        assert f"{slot}-profile:/home/neko/.config" in section, f"{slot}: profile volume changed"
        assert f"{slot}-downloads:/home/neko/Downloads" in section, f"{slot}: downloads volume changed"
    assert text.count("sessions:/data/sessions") == 3, "expected router plus two slot archive mounts"
    print("PASS W3-1 durable owner-archive mounts")


if __name__ == "__main__":
    main()
