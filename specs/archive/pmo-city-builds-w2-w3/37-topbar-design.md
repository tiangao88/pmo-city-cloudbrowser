# 37 — Unified Top Bar Design (LOCKED)

**Status:** LOCKED — 2026-08-22, Tigo chat approval ("yes lock the design now").
**Next step:** implementation (router `_top_bar`, title-proxy, downloads-api) on Tigo's go.

## 1. Requirement (Tigo, 2026-08-22)

Right side of the top bar, on **every** surface, in this order:

`CloudFiles <sep> Secrets <sep> Shared <sep> logged-in email`

- **"Shared"** = new pill: text "Shared" (green) or "Not Shared" (red), reflecting GrantHub state; clicking it navigates to GrantHub.
- Must apply to: CloudBrowser **session header** (neko, via title-proxy), CloudBrowser **queue page** (router), CloudBrowser **landing page** (router), and **CloudFiles** (downloads-api).
- CloudFiles-specific: `<title>` must read "CloudFiles" (currently "CloudBrowser"); top-left wordmark must read "CloudFiles"; the right-side CloudFiles link is replaced by a **CloudBrowser** link (navigate back to the browser).

## 2. Design (locked)

### 2.1 Layout — all surfaces

- **Left:** brand logo + per-surface wordmark (unchanged).
- **Right, fixed order:** `[📁 CloudFiles] ⏐ [🔒 Secrets · 🔗 Shared] ⏐ <email>`
- **Blocks:** CloudFiles is its own block; **Secrets + Shared are ONE block (no separator between them)**; email is right-most.
- **Separators:** 1px vertical rule, `rgba(255,255,255,.15)`, ~14px tall, margin 6px — placed **between CloudFiles and Secrets**, and **between Shared and email**. No separator inside the Secrets·Shared block.
- **Pills:** existing style (12px, `rgba(255,255,255,.08)` bg, radius 4px, hover `.2`).
- **Email:** right-most, 13px, `rgba(255,255,255,.72)`, non-interactive (unchanged).

### 2.2 Shared pill (GrantHub)

- Icon: 🔗 (title-proxy may use FA `fa-share-nodes`).
- Text/color: **Shared** `#22c55e` (green) / **Not Shared** `#ef4444` (red).
- Click: navigate to GrantHub — `https://cloudbrowser.dev01.pmo.city/connect` (spec 34, line 37).
- **State source:** GrantHub status (spec 34). Until a status endpoint is wired, the pill defaults to **Not Shared** (red) — never a false green.

### 2.3 Cross-navigation

- CloudBrowser surfaces → CloudFiles pill targets `FILES_URL`.
- CloudFiles surface → pill reads "CloudBrowser" and targets the browser origin (`BROWSER_URL`).

### 2.4 Branding per surface

- CloudBrowser surfaces: wordmark **CloudBrowser** (bold C + B); title "CloudBrowser" (session: "CloudBrowser: {email}").
- CloudFiles surface: wordmark **CloudFiles** (bold C + F); title "CloudFiles".

### 2.5 CloudFiles queue — recommendation (open, see §5)

**No queue for CloudFiles.** It serves the downloads view only — lightweight, no slot CPU — so it stays accessible at all times: no slot acquisition, no session limit, no reaper. The queue remains a CloudBrowser concept.

## 3. Surface matrix

| Surface | Wordmark | Title | Right side (order) |
|---|---|---|---|
| Landing (router) | CloudBrowser C+B | CloudBrowser | CloudFiles ⏐ Secrets · Shared ⏐ email |
| Queue (router) | CloudBrowser C+B | CloudBrowser | CloudFiles ⏐ Secrets · Shared ⏐ email |
| Session header (title-proxy) | CloudBrowser C+B | CloudBrowser: {email} | CloudFiles ⏐ Secrets · Shared ⏐ email |
| CloudFiles (downloads-api) | CloudFiles C+F | CloudFiles | CloudBrowser ⏐ Secrets · Shared ⏐ email |

## 4. Implementation map (on go)

**As-is notes:** downloads-api right side is currently `email · Secrets · CloudBrowser`
(title "Cloud Files" in repo; live deployed copy lags with "CloudBrowser" — both must be
redeployed). router `_top_bar` order is currently `Secrets · CloudFiles · email`; landing
page got its bar at `210ac6b`. title-proxy order: `CloudFiles · Secrets · email`.

- **router `_top_bar()`** (`router-v2.py`): reorder pills, add separator, add Shared pill; fetch GrantHub state (`GET {GRANTHUB_URL}/status` or spec-34 endpoint); error/404 → Not Shared. New env `GRANTHUB_URL`.
- **title-proxy.py:** same order + separator + Shared pill; per-surface `<title>`.
- **downloads-api.py:** wordmark/title → CloudFiles; right side per matrix (CloudBrowser · Secrets · Shared · email).
- One shared CSS token set (separator, pill colors) duplicated across the three files — no shared asset pipeline (keep in sync by convention).

## 5. Open items

1. **CloudFiles queue:** recommended **NO** (§2.5) — needs Tigo confirm.
2. **Shared state endpoint:** exact GrantHub status path to pin at implementation (spec 34) — until then, Not Shared default.
