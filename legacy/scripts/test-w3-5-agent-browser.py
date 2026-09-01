#!/usr/bin/env python3
"""Contract checks for the isolated W3-5 agent-browser PoC record."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "specs"


def check(name, condition):
    print(("PASS " if condition else "FAIL ") + name)
    return condition


def main():
    scope = (SPECS / "28-w3-scope.md").read_text(encoding="utf-8")
    roadmap = (SPECS / "08-roadmap.md").read_text(encoding="utf-8")
    report = (SPECS / "84-w3-5-agent-browser-poc.md").read_text(encoding="utf-8")

    checks = [
        ("roadmap records W3-5", "W3-5 isolated agent-browser PoC is complete" in roadmap),
        ("scope keeps later rollout gated", "### W3-6" in scope and
         "- [ ] Roll out beyond the W2 pilot users." in scope),
        ("scope marks W3-5 complete", "### W3-5" in scope and
         "**Status: COMPLETE" in scope),
        ("poc is isolated", "isolated" in report.lower() and
         "dedicated Chrome" in report),
        ("poc has executed evidence", "agent-browser 0.35.2" in report and
         "browser-use baseline" in report and "PASS" in report),
        ("cdp attach verified", "connect 9333" in report and
         "Chrome/151.0.7922.34" in report),
        ("deterministic actions verified", all(term in report for term in
         ("snapshot", "@e2", "click", "fill", "read"))),
        ("evidence capabilities verified", all(term in report for term in
         ("HAR", "axe-core", "WebM", "trace", "diff"))),
        ("owner binding remains explicit", all(term in report.lower() for term in
         ("owner", "isolation", "credential"))),
        ("recommendation is explicit", "RECOMMENDATION" in report and
         "adopt" in report.lower() and "production" in report.lower()),
        ("no live fleet mutation", "no live fleet" in report.lower() and
         "no credentials" in report.lower()),
    ]
    passed = sum(check(name, ok) for name, ok in checks)
    print(f"{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
