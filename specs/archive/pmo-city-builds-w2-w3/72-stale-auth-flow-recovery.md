# 72 — Stale Authentik flow recovery (2026-08-27)

Status: **IMPLEMENTED — LOCAL TESTS GREEN; LIVE DEPLOYMENT PENDING**

## Incident

A returning `spike-user@aikumi.pro` session was stuck on an Authentik MFA
screen instead of reaching the CloudBrowser surface. The browser profile's
`tab-snapshot.json` contained the Authentik `/if/flow/...` URL, so every wake
restored the old, transient authentication flow. A second live path could
leave Chrome running with only `chrome://newtab/`; the same-owner wake returned
`already up` without invoking the restore/homepage consumer.

## Fix

`restart-api.py` now:

- treats Authentik `/if/flow/` and `/application/o/authorize` URLs on the
  allowlisted auth hosts as transient SSO state, alongside `/error`;
- filters those URLs both when writing snapshots and when loading old snapshots;
- on a same-owner wake with Chrome running but zero real HTTP(S) tabs, resets
  the one-restore-per-Chrome-start guard and starts the existing restore
  consumer; it does not touch the profile or create/evict a tab directly.

The restore consumer then applies the established policy: restore a valid
snapshot if present, otherwise open the configured homepage as the zero-tab
fallback.

## Regression tests

`test-restart-api-tabs.py` now covers the auth-flow snapshot regression and the
same-owner zero-tab wake path in addition to the existing homepage semantics:
**5/5 passed**.

`test-spec72-auth-flow-and-wake.py` independently exercises the two incident
behaviors: **3/3 passed**.

The existing spec-65 regression remains green under the canonical CDP venv:
**ALL PASS**. Python compilation of the changed scripts also passes.

## Deployment gate

Before live deployment:

- copy the changed `restart-api.py` and focused tests into the canonical repo;
- commit and push;
- deploy only `cb-fleet-v2`;
- verify the scripts volume hash, container health, Chrome/CDP, snapshot contents,
  and the spike-user route without disturbing an active human session.
