# D10 — Denial-path verification results (35)

**Status: ✅ DONE (2026-08-21)** · 2026-08-21 ·
Gate: W2 DoD item 10 — *"Denial path (non-member → clean denial
403-equivalent; member regression check)"* (amended 2026-08-21, Tigo —
see §4; 27-w2-deltas.md §C).

## 1. Objective

Prove that an authenticated user **outside the allowed group** cannot reach
the cloud-browser viewer or the files domain, while a **member** still gets
in. Test account **A3** (`spike-user2`, created by Tigo 2026-08-21, same
password as `spike-user` — sourced from Vaultwarden item
`cloudbrowser-w1-test`, fetched in-process via `bw` CLI, never printed).

## 2. Method

Headless Playwright through the **full SSO chain** (no shortcuts, no
bypassed layers):

```
https://cloudbrowser.dev01.pmo.city
  → 302  auth.pmo.city/login (tinyauth-pmo gate)
  → 302  auth.aikumi.app/application/o/authorize/ (Aikumi Connect, OIDC
         client D6KUzbRAJyv2MK8vMq4g7Y8YSymW4tau)
  → 302  flows/-/default/authentication/
  → 200  Authentik flow SPA (shadow-DOM stage: ak-stage-identification;
         fields filled via Playwright locators — pierce shadow roots)
  → outcome (deny page OR callback → viewer)
```

The Authentik identification stage renders as **web components with shadow
DOM** (`AK-STAGE-IDENTIFICATION`, `AK-FLOW-INPUT-PASSWORD`); plain
`document.querySelector` does not pierce it — Playwright locators do.
Field: "Email or Username" + "Password" + "Log in".

## 3. Results (live, 2026-08-21)

| # | Test | Outcome | Evidence |
|---|---|---|---|
| 1 | **Non-member** `spike-user2` → `cloudbrowser.dev01.pmo.city` | ✅ **DENIED** | Authentik page: title "Permission denied", body "Permission denied \| spike-user2 \| Not you? \| Request has been denied. \| Powered by authentik". Final doc HTTP **200**. No redirect to viewer. |
| 2 | **Non-member** `spike-user2` → `cloudfiles.dev01.pmo.city` | ✅ **DENIED** | Same Authentik permission-denied page (same OIDC client id). |
| 3 | **Member** `spike-user` → `cloudbrowser.dev01.pmo.city` | ✅ **ACCESS** | Explicit-consent flow → tinyauth callback → `https://cloudbrowser.dev01.pmo.city/` **200**, viewer loading ("Loading https://cloudbrowser.dev01.pmo.city/"). |

**Effective gate:** the **Authentik application policy** bound to the OIDC
client (`D6KUzbRAJyv2MK8vMq4g7Y8YSymW4tau` — the same client serves both
`cloudbrowser` and `cloudfiles` tinyauth apps) denies `spike-user2` at the
`/application/o/authorize/` step — **before** the OIDC callback ever
completes, so tinyauth's own group middleware (`oauth.groups=PMOC_Users`,
set in the fleet compose labels) is a second layer that is never reached.

## 4. The nuance: deny page is HTTP 200, not 403

Authentik renders the application-access denial as a **200** page
("Permission denied / Request has been denied"). The DoD says "clean 403".

- **DECISION (2026-08-21, Tigo): Option A accepted** — the Authentik
  deny page **is** the clean denial: deterministic, identical on both
  domains, no viewer access, no data exposure. **Not** a literal HTTP
  403; the DoD wording is amended: *"clean denial (403-equivalent)"*.
- Option B (relax Authentik policy → tinyauth group middleware 403) was
  considered and **rejected for now** — extra config on `auth.aikumi.app`
  for no functional gain. Revisit if a downstream consumer ever requires
  a literal 403 status.

## 5. Notes / follow-ups

- `spike-user2` is a **non-member of PMOC_Users** — the policy bound to the
  OIDC client requires PMOC_Users (the same group tinyauth labels use).
- Member regression used `spike-user` (in PMOC_Users, widened by Tigo
  2026-08-17).
- Credential handling: password read via `bw unlock --passwordenv
  BW_MASTER_PASSWORD --raw` → `bw get item cloudbrowser-w1-test`, used
  only inside the test process; never echoed/logged.
- Test script: `/opt/data/d10-test.py` (agent-side, not in repo).
- W1 evidence ("non-member denied on both domains") reproduced on the
  **fleet** — closes E.3 gap #1 (D10 never tested against the fleet).
