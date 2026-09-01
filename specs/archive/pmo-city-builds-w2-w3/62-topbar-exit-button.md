# 62 — Top-bar Exit button: implemented (was undocumented W2 gap) (2026-08-25)

Status: **VERIFIED LIVE** — the feature exists; this spec closes the
documentation gap. Commit: `(2418055)`.

## The gap (Tigo, 2026-08-25)

> "In the past, we discussed an exit session button which was in the tab
> bar, and that we were supposed to move up to the top bar. I don't see
> any of those buttons on the interface. Can you search whether this has
> been implemented or not?" → "This was to be done in W2 and it was never
> shown in our to-do list, so that's a gap. Implement it, let's test it."

## History — implemented in code, never documented

1. **spec 32 (`963c20b`, 2026-08-22)** — Exit button in the TAB BAR:
   confirm popup → `SELF_RELEASE` → slot `/release` → router archives
   `reason=released` + re-offers slot (harness spec32/41 tests).
2. **spec 41 (`a305d81`, same day)** — Tigo directed: **Exit moves OUT of
   the tab bar INTO the neko top bar** (right of the email). content.js
   v1.11.0: tab-bar `#exit` removed; **`ensureBarExit()` injects a ⏏
   button into `ul.menu` after the email pill** — but ONLY when
   `/fleet/my-status` says `state == "active"` (queue/landing/connect
   pages have no top-bar Exit by design). The tab-bar `exitpop` confirm
   popup + `SELF_RELEASE` handler were kept.
3. **The docs never recorded it** — spec 41's comment was code-only, so
   it vanished from the W2 to-do/deltas. This spec closes that.

## Live verification (slot-1, spike-user active session, 2026-08-25)

- Session page (`/?pwd=neko&usr=…`, neko shell): probe → `hasMenu: true,
  exitLi: true, emailLi: true` — the ⏏ Exit button IS rendered in the
  top bar, right of the email, with CloudFiles/Secrets/Shared pills.
- `/fleet/my-status` → `{state: "active"}` (the button's gate).
- `/queue/status` → `{status: "active", open_url: "/?pwd=neko&usr=…"}`.
- Full chain (code-traced): ⏏ click → `openExitPop` confirm popup →
  `SELF_RELEASE` → `fetch 127.0.0.1:9230/release` → snapshot+archive+
  wipe → router `reason=released` → slot freed, user re-queued →
  redirect to `/`.
- Not visible on: queue page, landing, `/connect` card (no `ul.menu`
  top bar there — by design; those pages have their own top bar without
  Exit).

## W2 to-do update

Added to `27-w2-deltas.md` Part 2 as **D16-adjacent / spec 62 row**:
✅ Exit button in the neko top bar (spec 32 → 41 → 62) — live-verified.

## Files

- `specs/62-topbar-exit-button.md` — this doc.
- No code change required (feature complete); docs + todo only.
