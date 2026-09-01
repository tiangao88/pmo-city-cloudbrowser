# 48 — Capture-surface UX: /connect & Secrets pills

> **Status: 2026-08-23 — SHIPPED & DEPLOYED (rev2).** Part of D3 (row 4).
> Tigo's queue-page feedback (2026-08-23) and a second pass (rev2, same day)
> landed the final pill treatment. **CloudFiles + Secrets are ALWAYS plain
> main-browser links (`target="_blank"`) on every surface** (files must be
> downloadable on the main computer); only the GrantHub Shared pill drives
> the kiosk (capture). The queue-page pending-goto intent was removed.

## Problem (resolved)

The original spec forced **every** pill (CloudFiles · Secrets · Shared/Not
Shared) through the kiosk (`/kiosk/open` + `goto`), because a vault unlocked
in a separate desktop tab is invisible to the broker. Tigo's review then
changed the Secrets treatment:

- **Secrets (Vaultwarden) must NOT be kiosk-forced.** Managing your vault is
  a *fast main-browser* task (password manager, autofill, own sign-in). The
  user should not be drawn into the embedded Chrome for it. So Secrets is
  always a plain `target="_blank"` link to `SECRETS_URL`.
- **Hiding pills on the queue page read as "removed".** Pills stay visible;
  CloudFiles (and Surface pills where meaningful) defer to the kiosk via a
  pending-`goto` intent; Secrets still opens in the main browser.
- **"Not Shared" has no kiosk to capture in while queued / on CloudFiles**,
  so the GrantHub pill is hidden in those two nests.

## Surface → pill matrix (SHIPPED rev2, 2026-08-23)

**CloudFiles + Secrets are ALWAYS plain main-browser links (`target="_blank"`)
on every surface** (Tigo 2026-08-23: "CloudFi should always open in the main
window browser because this is how we can download the files on the main
computer. If we open CloudFi inside the embedded Chrome, then there's no way
we can get the file out."). Files must be downloadable on the main computer.
Only the GrantHub Shared pill still enters the kiosk (capture happens there).

| Surface | Where it renders | CloudFiles | Secrets | GrantHub (Shared) |
|---|---|---|---|---|
| router **landing** (`_top_bar` variant `landing`) | user's desktop browser | **plain `target="_blank"`** to `FILES_URL` | **plain `target="_blank"`** to Vaultwarden | `goto` → enter kiosk at `GRANTHUB_URL` |
| router **queue** (`_top_bar` variant `queue`) | user's desktop browser | **plain `target="_blank"`** to `FILES_URL` | **plain `target="_blank"`** to Vaultwarden | **hidden** (no kiosk capture yet) |
| neko **session** (`title-proxy.py` `addTool`) | user's desktop browser (viewer) | **plain `target="_blank"`** (main=true) | **plain `target="_blank"`** (main=true) | `/kiosk/open` → kiosk tab at `GRANTHUB_URL` |
| **CloudFiles** page (`downloads-api.py`) | the kiosk (normal now) | — (n/a; the page **is** the surface) | **plain `target="_blank"`** to Vaultwarden | **hidden** (kiosk-rendered, no re-capture need) |

CloudFiles as a plain link is safe while queued: the router routes
`cloudfiles.*` to the requester's assigned slot (else slot-1) and
downloads-api resolves **per-user by Remote-Email** (live slot dir if the
requester owns it, their own archived area, else empty) — never another
user's files, independent of slot.

Brand and pill order per spec 37: `📁 CloudFiles ⏐ 🔒 Secrets ⏐ 🔗 Not Shared | Shared` on bars where the Shared pill renders; right side always `... ⏐ <email>`.

## Mechanism notes

- `/kiosk/open` (router, `POST?url=`): requires `Remote-Email` + an
  active/offered slot; whitelists `FILES_URL`/`SECRETS_URL`/`GRANTHUB_URL` and
  same-origin `/` paths only, else 400; forwards `POST {slot-<k>:9230}/open-url`
  → 200 `{ok,slot}` / 502. (CloudFiles/Secrets no longer use it — only the
  Shared pill does.)
- `goto` entry (landing): `/ ?pwd=…&usr=…&goto=<url>`; after offer/take+wake
  the slatt 9230 `POST /open-url` opens it as the first kiosk tab. Only the
  landing Shared pill carries `goto` now.
- The queue-page `data-goto` pending-intent (`/queue/goto`, `_pending_goto`)
  was **removed** (rev2): queue-page pills are plain links; the entry opens a
  bare new tab.
- restart-api `POST /open-url`: CDP up → new kiosk tab immediately; CDP down
  → store `pending_start_url`, opened once by `restore_tabs()` after the
  snapshot restore, then cleared.

## Files touched (shipped `a5ca51b`)

- `router.py`: `_top_bar` per-variant pills (landing vs queue); Secrets plain
  `target=_blank`; GrantHub hidden on queue variant; CloudFiles entry/data-goto;
  `/kiosk/open` endpoint; `_open_url(goto=)`; `/` pwd/usr `goto` branch;
  `_queue_goto`/pending-`goto` plumbing; (`pending_goto` consumed on offer-take).
- `title-proxy.py`: `addTool(main)` flag — Secrets renders plain
  `target=_blank`; CloudFiles+Shared render `/kiosk/open` fetch.
- `downloads-api.py`: CloudFiles/bar template drops the GrantHub pill.
- `restart-api.py`: `POST /open-url` (+ `pending_start_url` in restore).
- `test-router.py`: harness updated; **104/104 green**.
- Doc: this file + `27-w2-deltas.md` D3 / spec 48 cross-reference.

## Validation

Deployed to cb-fleet (uuid okixw2...) via Coolify deploy + scripts-volume
write (router.py / title_proxy.py / downloads-api.py), md5-verified
byte-for-byte, router restarted, slot-1/2 title-proxy+downloads-api
supervisord-reloaded. Harness 104/104.

- **Live-verified (all four surfaces, 2026-08-23):** queue bar renders CloudFiles
  `data-goto` + Secrets plain link + **no** GrantHub pill; landing bar renders
  CloudFiles `goto` + Secrets plain link + Shared `goto`; session bar
  (title-proxy, slot-1) renders `🔒 Secrets` plain `target=_blank` (main=true)
  + `📁 CloudFiles` `/kiosk/open` (main=false) + `🔗 Not Shared` red `/connect`;
  CloudFiles bar (downloads-api) renders `🔒 Secrets` plain `target=_blank`
  and **no** GrantHub pill. `/router/health` ok.
