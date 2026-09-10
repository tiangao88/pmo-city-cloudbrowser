# Slot supervisor service

The supervisor implements owner-bound wake, suspend, stop and recreate through
the private browser transport. Binding adoption is serialized with lifecycle
operations; a stale running browser must stop before a different binding is
adopted. Failed stops must not silently allow takeover.

Implementation: `src/cloudbrowser/browser_slots/supervisor.py`,
`lifecycle.py`, and `src/cloudbrowser/router/control_api.py`. The trusted
router calls the private lifecycle API; callers do not choose an authoritative
owner. This is an implemented runtime, not a health-only placeholder.

Lifecycle metadata checks do not by themselves establish per-principal profile
storage across slot reuse. The real-browser A → B → A persistence/isolation
journey is a required gate in the
[roadmap](../../specs/proposals/v0.2/ROADMAP.md).
