# W1 POC — One-Page Summary (dev01)

**Closed 2026-08-17** · due Aug 23 · owner: Tigo / PMO City
Specs: `02-functional-requirements.md` (FR-1…FR-16) · evidence: `10-w1-status.md`

**Goal:** prove the full chain for ONE user on ONE browser + produce the
numbers W2–W4 depend on. All items verified live on dev01; DoD **8/8 ✅**.

## The chain (proven end-to-end)

- 🔗 **Link → SSO → browser** — click → Tinyauth SSO → Aikumi Connect → group
  gate (PMOC_Users) → live Chromium in seconds. Human-verified ×2 with
  screenshots.
- 🤖 **Agent control** — Hermes drives the same Chrome via the **browser-use
  library over CDP**, tunnel-free on the internal network: click, type,
  extract, screenshot. browser-use (latest) is the **token-efficient
  automation layer**: DOM pruning + compact element context ⇒ minimal LLM
  tokens per action — a **fundamental cost criterion** for the fleet.
- 💾 **Persistence** — cookies/logins survive container recreates (open tabs
  → W2).
- 📥 **Downloads** — flat store: 5 GB quota, 90-day retention, ClamAV scan
  at ingest (EICAR → quarantined). Retrieval in chat via the agent
  (in-viewer file list → W2).
- 🔑 **Vaultwarden extension** — force-installed via policy, pinned to the
  toolbar, vault URL pre-set; first unlock is the user's master password.

## Verdicts

**Viewer — neko** (vs noVNC): WebRTC-native (audio, clipboard, sub-second
latency), Apache-2.0, crash self-healing (supervisord `startretries=5`,
Singleton cleanup). Engine pinned: Chrome for Testing 128.0.6613.137.

**RAM (FR-16)** — idle **431 MiB** → loaded **471 MiB** (Wikipedia); CPU
107–146 % idle, 244 % peak (encoder-bound at 1920×1080). Chrome 12
procs / 1068 MB RSS. **Recommendation: 2 GB `--memory` cap per browser at
deploy** + `MAX_RUNNING_BROWSERS` fleet lock.

**Broker — deterministic, non-LLM**: Vaultwarden → server-to-server CDP
form-fill; **plaintext never enters the LLM context**. OIDC session flow →
W2.

## Sovereignty

Single-tenant, EU residency ✅ — mother01 hosted in **Helsinki, FI**
(EU/GDPR); public IP 145.223.34.130 (Hostinger AS47583; geo-IP DB nominally
FR/Paris — both EU).

## DoD (W1)

| # | Item | Result |
|---|---|---|
| 1 | Link → SSO → browser | ✅ |
| 2 | Agent drives browser (browser-use over CDP) | ✅ |
| 3 | Download → ask agent → file in chat | ✅ (reworded 2026-08-17) |
| 4 | Quota + ClamAV | ✅ |
| 5 | One-page summary | ✅ this document |
| 6 | Migration to pmoc-lan, old stack destroyed | ✅ |
| 7 | Chrome resilience | ✅ |
| 8 | Vaultwarden extension pre-config | ✅ |

## W2 (pilot — Tigo + testers)

Restart-Chrome button · per-user unlock + hybrid 2FA · tab persistence ·
browser-use re-validation on the download flow (W1 demo-day used Playwright
fallback) · group-gate denial-path test · tooling image (xdotool/curl/jq) ·
2 GB `--memory` cap applied at deploy.
