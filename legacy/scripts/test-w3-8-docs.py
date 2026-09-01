#!/usr/bin/env python3
"""Focused contract checks for the W3-8 operational documentation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "specs"


def read(name):
    return (SPECS / name).read_text(encoding="utf-8")


def check(name, condition):
    print(("PASS " if condition else "FAIL ") + name)
    return condition


def main():
    scope = read("28-w3-scope.md")
    roadmap = read("08-roadmap.md")
    isolation = read("43-session-isolation-tests.md")
    audit = read("82-w3-8-operations-and-audit.md")
    install = read("83-w4-sovereign-installation-checklist.md")

    checks = [
        ("roadmap reconciles spec-43 live tests",
         "isolation tests T6–T10 (spec 43) are complete" in roadmap),
        ("scope has reconciliation record",
         "W3 reconciliation note (2026-08-31)" in scope),
        ("scope marks W3-8 complete",
         "## W3-8 — Operational and audit expansion" in scope
         and "**Status: COMPLETE" in scope),
        ("spec-43 records reconciliation",
         "Reconciliation record (2026-08-31)" in isolation),
        ("audit schema is secret-free",
         "secret-free" in audit.lower()
         and "password" in audit.lower()
         and "never" in audit.lower()),
        ("audit has identity and lifecycle fields",
         all(term in audit for term in ("event_type", "request_id", "owner_id",
                                        "slot_id", "outcome"))),
        ("audit has retention policy",
         "90 days" in audit and "audit" in audit.lower()),
        ("health and recovery paths documented",
         all(term in audit for term in ("/health", "/fleet/status", "/restart",
                                        "/fleet/rescue", "recovery"))),
        ("operator response is fail-closed",
         all(term in audit for term in ("do not", "credentials", "cookies",
                                        "owner_mismatch"))),
        ("W4 checklist has secret and isolation gates",
         all(term in install for term in ("secret", "per-user", "isolation",
                                          "rollback", "Coolify"))),
        ("W4 checklist is explicitly not deployment approval",
         "not a deployment approval" in install.lower()),
    ]
    passed = sum(check(name, ok) for name, ok in checks)
    print(f"{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
