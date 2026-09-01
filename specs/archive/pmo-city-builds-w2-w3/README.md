# Cloud Browser — Specs

> Status: **refactor/specification reset — proposed for review 2026-09-01**.
> W2 is complete. W3 is active, with W3-1 partial/not proven on the strict
> authenticated-surface leg. The original baseline requirements remain below;
> the new refactor entry point is [README-refactor-reset.md](README-refactor-reset.md).
> No implementation, deployment, restart, credential rotation, or fleet
> mutation is authorized by the proposal documents.

## Spec index

| File | Contents | Status |
|---|---|---|
| [00-clarifying-questions.md](00-clarifying-questions.md) | All open questions (naming, scope, UX, security, ops) + **Vaultwarden batch** + **download storage batch (I)** + **LLM connectivity batch (J)** | ✅ **ALL ANSWERED 2026-08-16** — A–J closed; only POC-validated values remain (viewer choice, capacity numbers) |
| [decision-gate.md](decision-gate.md) | **Gate 1 — THE 5 blocking questions before implementation** | ✅ **CLOSED 2026-08-15 — all 5 answered** |
| [decision-gate-2.md](decision-gate-2.md) | **Gate 2 — next 5 questions** (browser multiplicity, token lifecycle, 2FA, viewer scope, fleet capacity) | ✅ **CLOSED 2026-08-16 — all 5 answered** |
| [01-product-overview.md](01-product-overview.md) | One-sentence product, personas, goals | planned |
| [02-functional-requirements.md](02-functional-requirements.md) | FRs 1–16 incl. **deterministic credential broker (FR-9)**, **single-IdP OIDC token flow (FR-10)**, **transversal agents (FR-14)**, **viewer (FR-15)**, **fleet capacity (FR-16)** | draft — FR-2/4/5/6/9/10/11/12/13/14/15/16 decided; batch 2 folded 2026-08-16 |
| 03-user-experience.md | Link flow, SSO, viewer UX, 2FA handoff | planned |
| 04-architecture.md | Topology, identity (Tinyauth), security model | planned |
| 05-non-functional.md | Performance, fleet sizing, audit, GDPR | planned |
| 06-data-and-secrets.md | Profile volumes, Vaultwarden access, tokens, retention | planned |
| [07-agent-api.md](07-agent-api.md) | **MCP surface for Hermes — full control (D1)** | ✅ **baseline decided 2026-08-16; refactor security contract proposed 2026-09-01** |
| [README-refactor-reset.md](README-refactor-reset.md) | **Refactor entry point: PRD, product boundary, and planning reset** | **PROPOSED FOR REVIEW — 2026-09-01** |
| [85-credential-broker-prd.md](85-credential-broker-prd.md) | **Generic deterministic credential broker PRD** | **PROPOSED FOR REVIEW — 2026-09-01** |
| [86-product-boundaries.md](86-product-boundaries.md) | **Cloud Browser / broker / agent / control-plane boundaries** | **PROPOSED FOR REVIEW — 2026-09-01** |
| [87-broker-security-model.md](87-broker-security-model.md) | **Broker threat model, capabilities, denylist, and acceptance tests** | **PROPOSED FOR REVIEW — 2026-09-01** |
| [08-roadmap.md](08-roadmap.md) | **POC → pilot → CRMOC → MVP (E3: 4 weeks, live ≤ 2026-09-13)** | ✅ **decided 2026-08-16** — 4-week plan, risks, MVP definition of done |
| [09-viewer-evaluation.md](09-viewer-evaluation.md) | **Viewer component research (2026-08-16): noVNC MPL-2.0, neko Apache-2.0, KasmVNC GPL-2.0 excluded** | ✅ done — POC spike decides noVNC vs neko |
| [10-w1-status.md](10-w1-status.md) | **W1 status + Definition of Done** (SSO chain, agent control, persistence, capacity, incident log, tooling) | ✅ **W1 CLOSED 2026-08-17** — 8/8 DoD |
| [18-w1-summary.md](18-w1-summary.md) | **W1 one-page executive summary** (viewer + RAM + broker verdicts, EU residency, DoD, W2 scope) | ✅ delivered 2026-08-17 (due Aug 23) |
| [16-capacity-measurements.md](16-capacity-measurements.md) | **FR-16 numbers** (idle/loaded RAM+CPU, 2 GB cap recommendation) | ✅ measured 2026-08-17 |
| [17-viewer-preconfiguration.md](17-viewer-preconfiguration.md) | **W1 implemented pre-config**: CfT pin, CDP relay, Bitwarden force-install/pin/vault-URL envelope, tooling inventory | ✅ implemented + verified 2026-08-17 |
| [19-viewer-test-findings.md](19-viewer-test-findings.md) | **Live test-session findings (2026-08-17 CRM)**: canvas-fit bug (Chrome chrome eats 1080 px → footers below fold), CfT notice no-dismiss, CDP-capture trap, browser-use tab-switch flake, translate popup, Bitwarden popups, kiosk fixes | ✅ recorded 2026-08-17 — fix list feeds W2/W4 |
| [20-w2-dod.md](20-w2-dod.md) | **W2 Definition of Done — OFFICIAL** (pilot Aug 24–30): roadmap inventory of all W2-deferred items (R1–R14) + 14 DoD items D1–D14, each verified against FRs + W1 evidence; SME framing (Tigo = SME, CRM workflow); open points for kickoff | ✅ **OFFICIAL 2026-08-17 (Tigo)** — reference definition of W2 |
| [21-w2-autonomy.md](21-w2-autonomy.md) | **W2 autonomy register**: per-DoD-item execution matrix (A = agent alone 7 items / P = agent+Tigo 7 items), standing grants G1–G5, boundaries (never without Tigo), new asks A1–A7 | ✅ **approved 2026-08-17 (Tigo)** |
| [22-w2-progress.md](22-w2-progress.md) | **W2 execution log**: D4/D6/D7/D12 done + verified 2026-08-17 (kiosk+CfT notice fix, restart API + watchdog self-heal, browser-use tab-switch + download re-validation, translate-off + popup janitor); remaining D-items and needs from Tigo | 📌 live — updated per work batch |
| [34-granthub.md](34-granthub.md) | **GrantHub — per-user revocable vault grant** (design 2026-08-21): the only component that touches a user vault key; TinyAuth-only SSO; wrapped user key valid-until-revoked; auto-re-minted short-lived broker sessions | 📌 **design draft** — links FR-9/FR-10, D15 |
| [35-d10-results.md](35-d10-results.md) | **D10 denial-path results (2026-08-21)**: non-member denied on both domains (Authentik page, HTTP 200 = clean denial per amended DoD); member regression OK | ✅ done 2026-08-21 |
| [36-spec31-results.md](36-spec31-results.md) | **Spec 31 queue + session-limits results log** (live): queue engine, offer grace, countdowns, lapsed-offer re-render (§23), session limit 30→15 (§24) | 📌 live — §1–§24 |
| [37-topbar-design.md](37-topbar-design.md) | **Spec 37 unified top bar design (LOCKED)**: CloudFiles ⏐ Secrets·Shared ⏐ email on all 4 surfaces; C+B / C+F brand rule; Shared pill state | ✅ **locked 2026-08-21 (Tigo)** — implemented |
| [38-status-2026-08-22.md](38-status-2026-08-22.md) | **Status 2026-08-22**: all cosmetic changes (C1–C9) + functional clarifications (F1–F9) with commits; W2 DoD position (9 ✅ · 2 🟡 · 1 🔄 · 3 ⏸); live fleet state | ✅ written 2026-08-22 |
| [39-wedged-neko-rescue.md](39-wedged-neko-rescue.md) | **Spec 39 wedged-neko auto-rescue (LOCKED)**: watchdog escalation (stuck-LOG-IN counter → `/fleet/rescue`) → slot `supervisorctl restart neko` (app-only, profile preserved); 2-rescue ceiling then alert | ✅ **locked 2026-08-22 (Tigo)** — pending implementation |
| [41-session-isolation-incident.md](41-session-isolation-incident.md) | **🔴 SECURITY INCIDENT 2026-08-22 — cross-user session leak**: wake-storm profile swap (PMBOK spike-user → montigaud); evidence timeline, root cause, impact | ✅ **investigated; fix in 42** |
| [42-session-isolation-fix.md](42-session-isolation-fix.md) | **Fix: no profile swap under live Chrome** — do_wake stops Chrome on user switch; suspend pid-guard; router wakes on take only; `.archive-user.json` marker; purge | ✅ **locked 2026-08-22 (Tigo)** — implemented |
| [43-session-isolation-tests.md](43-session-isolation-tests.md) | **Isolation regression suite (T1–T10)**: storm replay, marker-tab isolation, same-user resume, archive integrity sweep | 📌 run after fix deploy |
| [44-o6-error-page.md](44-o6-error-page.md) | **O6 — tab bar on error pages**: `webNavigation.onErrorOccurred` → bundled `error.html` (failure card + Retry/Back/Home + full tab bar); ERR_ABORTED/subframe filters; tab bar v1.12.0 | ✅ **implemented + live-verified 2026-08-22** |
| [45-isolation-stale-suspend.md](45-isolation-stale-suspend.md) | **🔴 SECURITY INCIDENT 2026-08-22 (3rd, spec 41/43 class)**: stale `_suspended` no-op + force-release handed the next user a live Chrome; fixes: stale-flag teardown + `_slot_clean` take guard | ✅ **deployed + verified** (commits `f19a10c`, `86ac441`) |
| [46-offer-take-wake.md](46-offer-take-wake.md) | **Offer-take never woke Chrome** (latent spec-42 bug) + **dirty freed-slot wedge**: take now wakes the slot; reaper self-heals dirty slots before offering; harness 94/94 | ✅ **deployed + verified** (commit `596bb72`) |

## How to read this

- Files are numbered; **00** is the gate — nothing below is final until the
  questions are answered.
- The design proposal (`../design-proposal.md`) remains the entry point /
  overview; these specs carry the detail.
