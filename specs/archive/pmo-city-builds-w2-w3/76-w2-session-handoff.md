> **Scope correction (2026-08-28):** W2 closes only with retained rows green and pilot sign-off. **D3/D15 is GREEN and closed for W2.** D13 is W3-3; strict D15 authenticated-surface continuity is W3-1.

# W2 Session Handoff — 2026-08-27

Use this file to resume CloudBrowser W2 work after a context reset. The repository is the source of truth. Do not infer state from an earlier chat.

## Authoritative roadmap and order

The official W2 dependency/priority order is `specs/27-w2-deltas.md` §F, especially lines headed:

> **2026-08-22 (Tigo): the W2 todo list is rebuilt on technical dependencies only — no pilot-criticality weighting.**

Always present and execute the list in that exact order. Do not reorder by D-number.

## Repository and deployed target

- Repository: `/workspace/pmo-city-builds`
- CloudBrowser directory: `internal/luna/tools-considered/cloud-browser-service/`
- Branch: `main`
- Current synchronized branch: `main` (latest D15 evidence commit is recorded after live verification; verify the final pushed tip with `git rev-parse origin/main`)
- Service: `cb-fleet-v2`, UUID `okixw2fxnwn1lakxvxajodww`
- Host: `mother01.on-ai.sbs`
- Only this dev service is authorized for CloudBrowser deployments.
- Never expose credentials in commands, logs, files, or chat.

## Dependency status

1. **O6 — tab bar on error pages:** ✅ done/live-verified.
2. **D6 — agent/browser-use against a real slot:** ✅ done/live-verified.
3. **GrantHub GH.1–GH.8:** ✅ done/live-verified.
4. **D3/D15 — broker OIDC flow and slot port:** 🟡 mostly done. Remaining: D3.5 dedicated A2 IdP-client qualification and final non-secret audit record; D15 owner-bound live tests below.
5. **D2 — hybrid 2FA:** ✅ done/live-qualified, autonomous and chat-assisted.
6. **D15 B — TinyAuth session health and proactive renewal:** 🟡 code reviewed, committed, deployed; owner-bound proactive-renewal live qualification remains. The owner-bound recreate run below retained the exact cookie and broker healthy state, but had no trusted application tab.
7. **D15 C — restart/recreate resilience:** 🟡 spec-77 recreate recovery PASSED live 2026-08-28 (owner-bound boot hint restored `spike-user` on slot-1 with tabs, assignment recorded; ghost-offer livelock dead); strict authenticated application-surface qualification remains open because archives carry no live TinyAuth cookie (spec 56) — broker re-login deferred to W3.
8. **D1 — per-user acceptance/static-password retirement:** 🟡 isolation implementation and T1–T10 are green; two named pilots, wording reconciliation, and sign-off remain.
9. **D13 — screen-follow:** 🔴 decision/open. Recommendation: defer to W3 and keep stable 1280×720.
10. **D7 — CRM footer recheck:** ✅ done/live-verified.
11. **O2 — downloads UI wording:** 🔴 Tigo wording decision remains.

Passive alongside the chain:

- **D9 fleet soak:** 🟡 caps/tuning done; a source-backed uninterrupted three-day zero-manual-intervention verdict remains.

## D15 implementation/deployment state

Security remediation is committed/pushed:

- Commit `723a7fc` — `fix(cloudbrowser): harden D15 session verification`
- Final independent review: PASS, no blocker/high or material medium/low findings.
- Exact TinyAuth cookie: `tinyauth-session-39fcd0f6`, `.pmo.city`, `/`, Secure, HttpOnly.
- Explicit trusted origins: `https://pmo.city`, `https://cloudbrowser.dev01.pmo.city`, `https://cloudfiles.dev01.pmo.city`.
- CDP ambiguity/errors, duplicate cookies, stale owners, and assignment-generation changes fail closed.
- Fresh cookie is owner-validated through TinyAuth `/api/context/user`.

Live deployment completed after token rotation:

- Compose patched and only `cb-fleet-v2` redeployed.
- All five containers became healthy.
- Both slots received the D15 environment values.
- Reviewed `sso-broker.py` installed in shared scripts volume.
- Repo/live broker SHA-256 matched: `edffc1173bdc308e182a929740401fac45e86d7a5aa48a02dae902a8d8327fe4`.
- Both brokers were RUNNING.
- Both unowned slots were returned to clean suspended state.
- No active human session was interrupted.

## D15 status after spec-65 remediation and owner-bound qualification (2026-08-27)

- Test owner: `spike-user@aikumi.pro` (real test identity; no synthetic identity used).
- Spec-65 timer/MFA-loop remediation remains deployed only to `cb-fleet-v2`.
- Fresh owner reacquisition was observed before this qualification. The slot reported owner `spike-user@aikumi.pro`, Chrome running, `cdp_ok: true`, and the three existing tabs `https://atpa.asia/`, `https://agenticpmo.org/`, and `https://github.com/`.
- Read-only baseline found one exact TinyAuth cookie and no trusted application page because the existing tabs were external sites. The cookie was present; the authenticated application surface was therefore not independently proven by the tab/page predicate.
- `/restart` qualification passed: HTTP 200; after 14 one-second polls, the owner remained assigned, Chrome was running, `cdp_ok: true`, and all three existing tabs were restored (order changed only). Read-only CDP inspection confirmed the tab set was unchanged and the exact TinyAuth cookie remained present; trusted application page count was zero.
- Full recreate qualification then passed for infrastructure: the authorized recreate of only `cb-fleet-v2` completed with all five containers healthy. Slot-1 recovered the owner, Chrome, `cdp_ok: true`, and the same three tabs; slot-2 recovered unowned with the homepage baseline. Both slots had the customization receipt and policy gate present.
- Post-recreate read-only inspection again found one exact TinyAuth cookie, no trusted application page, unchanged tab set, and `authenticated_surface: not-proven` under the strict cookie-plus-trusted-page predicate. The owner marker and browser/tab recovery passed, but application authentication cannot be claimed from these external tabs alone.
- Broker log after recreate classified the session as `healthy` with a remaining TTL and reported `session refresh pending — no trusted app tab`. No active human session was interrupted and no tab was created or evicted by verification.

**Qualification result:** infrastructure, owner persistence, broker restart, and snapshot/tab recovery passed. The strict D15 authenticated-surface criterion remains open because the reacquired session contained no trusted PMO City application tab at the destructive boundary or afterward. A final pass needs one existing trusted PMO City application tab while the owner session is active, then the same `/restart` and full-recreate sequence.

## D15 C rerun evidence — 2026-08-28

Tigo authorized a fresh recreate/redeploy of only `cb-fleet-v2` after the
leftover slot-2 test session was identified. The leftover `d6-agent@aikumi.pro`
assignment was explicitly suspended first; readback showed slot-2 unowned,
suspended, Chrome stopped, `cdp_ok: false`, and no tabs.

Before the destructive boundary, slot-1 held the real test identity
`spike-user@aikumi.pro`. Read-only baseline evidence showed Chrome running,
`cdp_ok: true`, one exact TinyAuth cookie (`tinyauth-session-39fcd0f6`,
`.pmo.city`, `/`, Secure, HttpOnly), TinyAuth context HTTP 200 authenticated as
the intended owner, and one trusted application page at
`https://cloudfiles.dev01.pmo.city/`.

The authorized recreate was triggered through the Coolify service endpoint for
`cb-fleet-v2` and completed with all five components `running:healthy`.
Afterward, however, slot-1 was suspended and ownerless: Chrome `STOPPED`,
`cdp_ok: false`, and no tabs. Its CDP endpoint reset/closed connections before
the post-recreate cookie/page inspection could complete. The router state
readback contained no active users, slots, or sessions; the test owner had
fallen back into the human queue after an offer expired. Slot-2 recovered as
an unowned running homepage baseline before the explicit cleanup readback.

**Verdict:** infrastructure recreate = **PASS**; strict D15 C owner-bound
authenticated session/tab recovery = **NOT PROVEN / FAIL**. The failure is now
at the post-recreate slot-1 Chrome/CDP recovery path, not at the pre-recreate
TinyAuth baseline. No active human session was interrupted and no tabs were
created or evicted by the read-only checks.

Evidence artifacts (local operator workspace):

- `/opt/data/d15-c-baseline-before-recreate.json`
- `/opt/data/d15-c-recreate-trigger-authorized-response.json`
- `/opt/data/d15-c-service-after-authorized-recreate.json`
- `/opt/data/d15-c-slot-9230-final.json`
- `/opt/data/d15-c-slot-9231-final.json`
- `/opt/data/d15-c-post-recreate-auth-final.log`
- `/opt/data/d15-router-state-post-recreate-final.json`
- `/opt/data/d15-broker-logs-post-recreate.txt`

## D15 C closure — spec 77 (2026-08-28, later the same day)

Root cause of the failing slot-1 recovery: an unbounded offer→expire livelock
between `montigaud@aikumi.pro` and `spike-user@aikumi.pro` (60 s grace too
short for either to take), plus an ownerless boot path with NO owner-bound
recovery. Fixed under [77-w2-recreate-recovery.md](77-w2-recreate-recovery.md)
and deployed to `cb-fleet-v2` only:

- **Ghost-offer backoff** — per-`(email, slot)` offer-expiry counter;
  `CB_OFFER_BACKOFF_THRESHOLD` (3) expiries within the window move the queue
  entry to `status=backed_off` (invisible to the offer scan), dropped after
  `CB_OFFER_BACKOFF_COOLDOWN_S`. Counter resets on a successful take.
- **Owner-bound boot hint** — a slot that boots ownerless with a real archive
  in `/data/sessions/<user>/` reports `pending_archive_owner` in `/health`;
  the router sweep (30 s) dispatches the standard `/wake` for that owner and
  RECORDS the assignment (users/slots/sessions). One-shot per boot (cleared
  on bind) + router one-shot memory per owner.

Local suite `test-router.py`: **124/124 green** (2 consecutive runs).

Live re-qualification on `cb-fleet-v2` (recreate of ONLY the service, both
slots pre-suspended ownerless):

- `[router] boot-hint wake slot-1 → spike-user@aikumi.pro` fired with NO
  human interaction ~2 min after the recreate; slot-1 `/health`:
  `user: spike-user@aikumi.pro`, `cdp_ok: true`, Chrome RUNNING,
  `pending_archive_owner: null` (hint consumed on bind).
- Router state recorded: `users {spike-user@aikumi.pro: 1}`,
  `slots {1: …}`, `sessions {…}`.
- Read-only CDP probe (tab set unchanged): 2 tabs restored from the archive
  snapshot (`https://pmo.city/` — trusted PMO City application — and
  `https://agenticpmo.org/`); `exact_tinyauth_cookie_metadata_count: 0` →
  `authenticated_surface: not-proven` (spec 56 strips identity cookies from
  archives; broker auto-re-login is W3 out of scope).
- `montigaud@aikumi.pro` livelock: 3 offer expiries → `backed_off` →
  dropped after cooldown; queue ended empty. Slot-2's armed hint was NOT
  dispatched (owner live on slot-1).

**Verdict:** spec-77 contract = **PASS** (owner-bound recreate recovery +
ghost-offer backoff, live-verified). D15 B/C status updated to: infrastructure,
owner, broker, and snapshot/tab recovery **PASS**; the strict
authenticated-surface criterion remains **open** by design (spec-56 cookie
strip + W3 broker re-login), pending a fresh owner-bound session with a
trusted application tab at the destructive boundary.

## Documents requiring synchronization after live closure

The following still contain stale pre-deployment/Coolify-401 language and must be updated only after evidence is collected:

- `specs/23-d15-sso.md`
- `specs/20-w2-dod.md`
- `specs/22-w2-progress.md`
- `specs/27-w2-deltas.md`
- `specs/47-w2-items-2-4-execution.md`
- `specs/08-roadmap.md` if the W2 summary/timeline changes

The D15 deployment/Coolify-401 language in the first three documents was updated on 2026-08-27 to record the healthy deployment and the inconclusive full-recreate qualification. The remaining tracker documents should be synchronized only when the fresh authenticated owner-bound test is closed.

Commit and push documentation plus evidence. Verify local HEAD equals `origin/main` and the working tree is clean.

## Immediate next action

Resume at **dependency row 4/6: D3/D15, specifically D15 B owner-bound live qualification**. Before touching a slot, inspect router state and both slot health endpoints. Do not interrupt an active owner. Use an existing real test identity; never enqueue synthetic identities into the live user-visible queue.
