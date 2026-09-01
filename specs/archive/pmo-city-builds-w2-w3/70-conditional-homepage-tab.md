# 70 — Conditional homepage tab persistence (2026-08-25)

Status: **DEPLOYED + VERIFIED**

## Report and live diagnosis

Tigo restarted an incognito client from zero and confirmed that the Exit UI
was correct, but a three-tab CloudBrowser workspace restored only two tabs.

Live evidence showed:

- montigaud's archive snapshot contained exactly `agenticpmo.org` and
  `exa.ai`;
- slot-1 logged `tab-restore: opened 2 tab(s) from snapshot`;
- the third reported tab was the configured homepage (`pmo.city`).

This was not another archive/snapshot-loss incident. The existing
`snapshot_tabs()` rule always filtered `HOME_URL`, even when the homepage was
one intentional tab in a larger workspace.

## Fine-tuned rule (Tigo approved)

- **Homepage alone:** it is the automatic zero-tabs fallback; do not persist
  it and do not restore a homepage-only historical snapshot.
- **Homepage plus at least one other restorable tab:** it is part of the
  user's workspace; persist and restore it in place.
- **No restorable snapshot:** `ensure_homepage()` opens exactly one homepage.
- Existing URL deduplication, SSO-error filtering and `TAB_LIMIT` remain in
  force.

## Implementation

`restart-api.py` now builds a deduplicated candidate list first. It keeps that
entire list, including `HOME_URL`, when at least one non-home URL exists;
otherwise it writes no snapshot. `load_snapshot()` mirrors the same semantic:
a mixed snapshot keeps the homepage, while a homepage-only snapshot resolves
to no restorable tabs and falls through to the single-homepage fallback.

## Regression test

`test-restart-api-tabs.py` covers:

1. homepage-only is not persisted;
2. homepage in a three-tab workspace is persisted in order;
3. mixed snapshots restore the homepage, homepage-only snapshots do not.

RED before implementation: **1/3 passed**.  
GREEN after implementation: **3/3 passed**.

## Deployment verification checklist

- [x] `restart-api.py` and the focused test are copied into the canonical repo.
- [x] Python compile and focused regression test pass from canonical files.
- [x] Full router regression harness remains green (**114/114** under the
      canonical `/opt/data/cdp-venv` test environment; a plain system-Python
      run reproduced the known spec-41 timing flake at 111/114).
- [x] Updated restart-api is copied to the fleet scripts volume with matching
      checksum (`68c47e79d7b7b17ce22a298ebfd97162`) and mode `755`.
- [x] Both restart-api processes were restarted to activate the code. The
      active slot-1 Chrome PID and its two tabs remained unchanged; no slot,
      Chrome or Coolify service restart/redeploy occurred. Both slot health
      endpoints returned HTTP 200 and both runtime scripts compiled.
- [x] Commit pushed to `main`: `386974d`.
