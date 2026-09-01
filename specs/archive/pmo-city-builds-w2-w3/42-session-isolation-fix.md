# Spec 42 — Session Isolation Fix: No Profile Swap Under a Live Chrome

> **Status: LOCKED for implementation (Tigo, 2026-08-22 — "patch and redeploy at will").**
> Fixes incident spec 41. Scope: `restart-api.py` (slot) + `router.py` (fleet) +
> archive hygiene. Verification: spec 43.

## 0. Design principle

> **A slot's Chrome process and its on-disk profile must always belong to the
> same user.** The only legal way to change a slot's user is:
> `stop chrome + stop title-proxy → restore archive (wipe+copy) → start
> chrome + start title-proxy`. Chrome never runs across a profile swap, and
> the router never asks a slot to change users until a human actually takes
> the slot.

## 1. Fix A — `restart-api.py do_wake()`: stop Chrome before a user switch

**Current behaviour (bug):**
```python
def do_wake(user: str) -> dict:
    global _suspended, _grace_until, _need_restore
    if not restore_user(user):            # wipes profile + copies archive
        ...
        wipe_slot_dirs()
    set_slot_user(user)
    _suspended = False
    _grace_until = None
    subprocess.run([SUPERVISORCTL, "start", CHROME_PROG], ...)   # "ERROR (already started)"
    subprocess.run([SUPERVISORCTL, "start", TITLE_PROXY_PROG], ...)
```

**New behaviour:**
```python
def _chrome_running() -> bool:
    return sup_status().get(CHROME_PROG) == "RUNNING"   # or pid check

def do_wake(user: str) -> dict:
    global _suspended, _grace_until, _need_restore
    cur = slot_user()
    if cur == user and _chrome_running() and not _need_restore:
        # Re-offer of the same user with a live chrome: nothing to do.
        # (Do NOT wipe/re-copy — the running chrome owns this profile.)
        _suspended = False
        _grace_until = None
        return {"ok": True, "note": "already up"}
    if _chrome_running() or _title_proxy_running():
        # User switch (or stale chrome from a previous user): stop BOTH
        # before touching the profile. This is the isolation invariant.
        subprocess.run([SUPERVISORCTL, "stop", CHROME_PROG], timeout=60)
        subprocess.run([SUPERVISORCTL, "stop", TITLE_PROXY_PROG], timeout=60)
        print(f"idle: wake user-switch {cur or '?'} -> {user} — chrome stopped", flush=True)
    if not restore_user(user):
        print(f"idle: no archive for {user} — fresh wake (empty profile)", flush=True)
        wipe_slot_dirs()
    set_slot_user(user)
    _suspended = False
    _grace_until = None
    subprocess.run([SUPERVISORCTL, "start", CHROME_PROG], ...)
    subprocess.run([SUPERVISORCTL, "start", TITLE_PROXY_PROG], ...)
    record_started_pid()        # see Fix B
```

**Notes**
- `slot_user()` reads `.slot-user.json` — the single source of "who does the
  disk profile belong to".
- The same-user early return prevents the wasteful wipe/re-copy that the
  offer storm was hammering.
- `_need_restore` (watchdog flag) forces a real restart when the watchdog
  queued a restore (tab restore depends on chrome PID change).

## 2. Fix B — `restart-api.py do_suspend()`: never snapshot another user's tabs

**Current (bug):** `snapshot_tabs()` runs unconditionally at the top of
`do_suspend()`, reading whatever Chrome is currently running.

**New:**
```python
def do_suspend(reason: str | None = None) -> None:
    global _suspended
    user = slot_user()
    if not user: ... return
    if _suspended: return
    pid_now = _chrome_main_pid()
    pid_wake = get_started_pid()          # recorded at last do_wake
    if pid_now is not None and pid_wake is not None and pid_now != pid_wake:
        # Isolation violation: the running chrome is not the one we started
        # for this user. Do NOT snapshot (would archive the wrong tabs);
        # clear any stale snapshot so a future restore can't resurrect them.
        print(f"idle: SUSPEND isolation guard — chrome pid {pid_now} != wake pid "
              f"{pid_wake}; snapshot skipped, stale snapshot cleared", flush=True)
        try: os.remove(SNAPSHOT_FILE)
        except FileNotFoundError: pass
    else:
        try: snapshot_tabs()
        except Exception as e: print(f"idle: pre-suspend snapshot failed: {e}", flush=True)
    ... (rest of suspend unchanged: stop chrome, stop title-proxy, archive, wipe, release)
```

**Notes**
- `get_started_pid()/record_started_pid()`: a module global `_started_pid`
  set in `do_wake()` right after `supervisorctl start chrome` succeeds
  (via `_chrome_main_pid()` after a short settle).
- If the guard fires, the archive still gets the profile (correct user —
  it was restored at wake), just no snapshot. The user's tabs are lost for
  that one suspend rather than leaked — **fail-safe bias**.

## 3. Fix C — `router.py`: wake only on TAKE, never on offer

**Current (bug):** the reaper fires `_offer_wake(k, email)` for every offered
queue entry (`threading.Thread(target=_offer_wake, args=(k, email))`), i.e.
the slot is woken *before* the human accepts. With a 60 s offer grace and
two queue heads alternating, this produced the wake storm.

**New:**
```python
# In the reaper's offer section: DELETE the _offer_wake spawn entirely.
# The slot stays suspended (chrome stopped, profile wiped) until the user
# actually takes the offer; the take path (queue take / GET /?pwd=...)
# already calls _wake_slot() -> POST /wake on the slot.
```

**Notes**
- The take path is already correct (router log: `offer taken by X → slot-1`
  followed by `GET /?pwd=...` and the slot `POST /wake` 200).
- Effect: an offered-but-unaccepted slot stays **cold** (0 CPU, no chrome).
  Session start latency after take: ~5 s (restore + chrome start) — same as
  the normal resume path today.
- `_offer_wake` / `_wake_slot_global` may remain for the take path or be
  pruned; the reaper call site is removed regardless.

## 4. Fix D — defense-in-depth: archive owner marker

- `archive_user()` additionally writes `.archive-user.json`
  `{"user": <email>, "ts": <unix>, "tabs": <count at archive>}` into the
  archive root (alongside `profile/` and `Downloads/`).
- `restore_user(user)` reads it first:
  - missing marker → **WARN** (archive from pre-fix era) but proceed (backward compat);
  - marker.user != requested user → **REFUSE restore** (log ERROR, return
    False → `do_wake` falls back to fresh wake with wipe).
- Marker is also how the test suite verifies archive integrity after a storm.

## 5. Fix E — purge contaminated archives (incident §5)

After the code fix is deployed:

1. `montigaud@aikumi.pro` archive:
   - remove PMBOK from `profile/tab-snapshot.json` (regenerate: keep only
     auth-flow URL if still present — it is montigaud's own login flow);
   - delete PMBOK rows from `profile/Default/History` (sqlite) and the
     matching `Favicons`/`Top Sites` rows;
   - delete `profile/Default/Sessions/Session_*` and `Tabs_*` (chrome
     session-restore files; regenerated on next close);
   - delete `wikipedia.org` cookies from `profile/Default/Cookies`;
   - add `.archive-user.json` marker.
2. `spike-user@aikumi.pro` archive: same treatment for the aikumi.news /
   montigaud-era traces (history rows + cookies), keep spike-user's own
   Wikipedia history (it is his).
3. Live slot-1 (montigaud): close PMBOK tab (done 20:0x), the snapshot on
   next suspend is regenerated from the correct chrome.

## 6. Out of scope (tracked elsewhere)

- Per-user cookie isolation *within* a profile (site-level) — not the bug.
- D1 static-password retirement (auth chain) — W2 row 8, separate spec.
- GDPR/retention policy for archives — W3+.
