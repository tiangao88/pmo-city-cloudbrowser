// Cloudbrowser Tab Bar — background service worker (MV3).
// Handles tab listing/switching/closing, per-tab
// navigation (back/forward/reload) and the "Relaunch Chrome" action
// for the kiosk viewer.
//
// v1.2.0 — staleness healing: on install/startup the worker probes every
// open tab and re-injects content.js where the script is missing or an
// older version runs (extension updates leave old content scripts on open
// tabs with a dead chrome.runtime bridge -> clicks silently die until the
// page is reloaded). Keep EXT_VERSION in sync with content.js VERSION.
// v1.3.0 — icon/order update; EXT_VERSION bump.
// v1.3.1 — pos toggle triangle; EXT_VERSION bump.
// v1.4.0 — consolidation: bookmarks + NEW_TAB removed (tab bar is pure
// navigation now; Vaultwarden/Files live in the client toolbar).
// v1.5.0 — spec 27 (2026-08-21): Home + Plus (URL) buttons and the tab
// limit. CONFIG values come from restart-api GET /config (compose env
// HOME_URL/TAB_LIMIT — MV3 cannot read env vars), cached in
// chrome.storage.local; built-ins are fallbacks. LIST_TABS now returns
// tabLimit so the content script can gray out Home/Plus at the limit.
// v1.6.0 — spec 27 S6 (2026-08-21, Tigo): at the tab limit, new tabs
// EVICT the least-recently-used real tab instead of blocking. Home/Plus
// stay enabled; the evicted tab's title is broadcast as a toast
// (TAB_EVICTED). chrome.tabs.Tab.lastAccessed (Chrome 121+) drives the
// LRU order; the active tab is never evicted.
// v1.7.0 — spec 27 S6 completion (2026-08-21, Tigo): the limit now also
// applies to tabs created NATIVELY — in-page target=_blank / window.open —
// not just via the bar's own Home/Plus buttons. chrome.tabs.onCreated +
// onUpdated(url) schedule a debounced enforce() (300 ms) which evicts the
// LRU inactive real tab when the count exceeds the limit; the
// freshly-created tab is never the victim. A startup trim removes
// pre-existing excess (session/snapshot restore at boot, or pre-fix
// leftovers).
//
// v1.11.0 — spec 41: Exit moved OUT of the tab bar into the neko top bar
// (right of the email). content.js no longer hosts #exit; SELF_RELEASE
// stays (the neko-bar button sends the same message).
// v1.12.0 — spec O6 (2026-08-22): tab bar on error pages. chrome-error://
// pages cannot run content scripts, so instead of scripting them we
// REPLACE the error page with a bundled extension page (error.html) that
// shows the failure + a functional tab bar (restart always reachable).
// v1.13.0 — spec 64 (2026-08-25): content.js gains the universal Exit
// fallback button (external pages only); SELF_RELEASE unchanged.
//
// CONFIG — template placeholders: substitute the real app URLs before
// deploy (the internal mirror repo carries the real values).
const EXT_VERSION = "1.13.1";
const CONFIG = {
  restartUrl: "http://127.0.0.1:9230/restart",
  configUrl: "http://127.0.0.1:9230/config",
  homeUrl: "https://pmo.city", // fallback — /config overrides
  tabLimit: 3                  // fallback — /config overrides
};

// Fetch the runtime config once at SW startup; never throws (defaults win).
async function loadConfig() {
  try {
    const r = await fetch(CONFIG.configUrl, { cache: "no-store" });
    if (r.ok) {
      const c = await r.json();
      if (typeof c.homeUrl === "string" && c.homeUrl) {
        CONFIG.homeUrl = c.homeUrl;
      }
      if (Number.isInteger(c.tabLimit) && c.tabLimit > 0) {
        CONFIG.tabLimit = c.tabLimit;
      }
      await chrome.storage.local.set({
        cbConfig: { homeUrl: CONFIG.homeUrl, tabLimit: CONFIG.tabLimit }
      });
    }
  } catch (_e) {
    /* restart-api unreachable (e.g. Chrome restarted first) — keep defaults */
  }
}

function visibleTabs() {
  return chrome.tabs.query({}).then((tabs) =>
    tabs
      .filter((t) => t.url && !t.url.startsWith("chrome://"))
      .map((t) => ({
        id: t.id,
        title: t.title || t.url,
        url: t.url,
        favIconUrl: t.favIconUrl || "",
        active: t.active
      }))
  );
}

async function activeTabId() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs.length ? tabs[0].id : null;
}

// v1.13.0 (spec 61): age-floor — never evict a tab the user has kept
// open for more than EVICT_AGE_FLOOR_MS. Eviction exists to make room
// for NEW work; a user's long-lived tabs (vault, inbox, CRM) are the
// session's state and must survive to the session-end snapshot.
const EVICT_AGE_FLOOR_MS = 10 * 60 * 1000; // 10 minutes

// v1.6.0 (spec 27 S6): LRU eviction. At the tab limit, a new tab closes
// the least-recently-used real tab instead of being blocked. The active
// tab is by definition the most recently accessed, so it can never be
// the LRU victim. v1.7.0: skipId — the tab that just appeared is also
// never a victim (a background-created window.open tab must not be closed
// the moment it was asked for).
async function evictLRU(skipId = null) {
  const tabs = await chrome.tabs.query({});
  const real = tabs.filter(
    (t) =>
      t.id != null &&
      t.id !== skipId &&
      t.url &&
      !t.url.startsWith("chrome://") &&
      !t.url.startsWith("chrome-extension://")
  );
  if (real.length < CONFIG.tabLimit) return null;
  const now = Date.now();
  let victim = null;
  for (const t of real) {
    if (t.active) continue;
    // v1.8.0: never evict a freshly created tab. Tab restore (D5) opens
    // several tabs within seconds of a Chrome restart; without this the
    // first restored tab is the LRU by the time the third one lands and
    // gets evicted at the limit (Tigo 2026-08-22: real tabs lost).
    if ((t.lastAccessed || 0) > now - 5000) continue;
    // v1.13.0 (spec 61): age floor — tabs opened before the floor are
    // the user's state, never eviction fodder.
    if ((t.lastAccessed || 0) < now - EVICT_AGE_FLOOR_MS) continue;
    if (!victim || (t.lastAccessed || 0) < (victim.lastAccessed || 0)) victim = t;
  }
  if (!victim) return null;
  const info = { title: victim.title || victim.url, url: victim.url };
  try {
    await chrome.tabs.remove(victim.id);
  } catch (_e) {
    return null;
  }
  return info;
}

// Open a URL in a new tab; evict the LRU tab first when at the limit.
async function openTab(url) {
  // v1.13.0 (spec 61): never duplicate an existing real tab — a second
  // copy of a surface the user already has open only feeds the eviction
  // pressure. Focus the existing tab instead.
  const tabs = await chrome.tabs.query({});
  const existing = tabs.find(
    (t) => t.url && t.url.split("#")[0].replace(/\/$/, "") === url.split("#")[0].replace(/\/$/, "")
  );
  if (existing && existing.id != null) {
    await chrome.tabs.update(existing.id, { active: true });
    return {
      ok: true,
      url,
      focused: true,
      evicted: false,
      evictedTitle: null
    };
  }
  const evicted = await evictLRU();
  await chrome.tabs.create({ url, active: true });
  if (evicted) broadcastToast(evicted);
  return {
    ok: true,
    url,
    focused: false,
    evicted: !!evicted,
    evictedTitle: evicted ? evicted.title : null
  };
}

// Tell every tab's content script (for its toast) which tab was evicted.
async function broadcastToast(info) {
  const tabs = await chrome.tabs.query({});
  const msg = { type: "TAB_EVICTED", title: info.title };
  for (const t of tabs) {
    if (
      !t.id ||
      !t.url ||
      t.url.startsWith("chrome://") ||
      t.url.startsWith("chrome-extension://")
    )
      continue;
    try {
      await chrome.tabs.sendMessage(t.id, msg);
    } catch (_e) {
      /* no tab bar on that page — fine */
    }
  }
}

// v1.7.0 — native-tab limit enforcement (spec 27 S6 completion).
// A page opening a link in a new tab (target=_blank / window.open) fires
// onCreated; navigation fires onUpdated(url) shortly after. Both schedule
// a debounced enforcement for that tab id — the 300 ms window absorbs the
// onCreated+onUpdated double-fire (and any subsequent title/favicon
// updates while the page settles) so we never evict twice for one tab.
const enforceTimers = new Map();

function scheduleEnforce(tabId) {
  if (enforceTimers.has(tabId)) clearTimeout(enforceTimers.get(tabId));
  enforceTimers.set(
    tabId,
    setTimeout(() => {
      enforceTimers.delete(tabId);
      enforceLimit(tabId);
    }, 300)
  );
}

async function enforceLimit(newTabId) {
  const evicted = await evictLRU(newTabId); // never evict the new tab itself
  if (evicted) broadcastToast(evicted);
}

// Startup trim: at SW start, if the count is already over the limit
// (session/snapshot restore at boot, or pre-fix leftovers like the 6-tab
// state seen live), evict down to the limit. Bounded loop as a guard.
async function trimExcess() {
  let guard = 0;
  let evicted;
  while ((evicted = await evictLRU(null)) && guard++ < 20) {
    broadcastToast(evicted);
  }
}

chrome.tabs.onCreated.addListener((tab) => {
  if (tab.id != null) scheduleEnforce(tab.id);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) scheduleEnforce(tabId);
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    switch (msg.type) {
      case "__PING__":
        return { version: EXT_VERSION };
      case "LIST_TABS":
        return { tabs: await visibleTabs(), tabLimit: CONFIG.tabLimit };
      case "OPEN_URL":
        // S3/S6: open a user-entered URL in a new tab (http(s) only).
        // At the tab limit the least-recently-used tab is evicted first
        // (never the active tab); the evicted title goes out as a toast.
        if (typeof msg.url !== "string") return { ok: false, error: "no url" };
        let target = msg.url.trim();
        if (!target) return { ok: false, error: "empty url" };
        if (!/^https?:\/\//i.test(target)) target = "https://" + target;
        if (!/^https?:\/\/.+/i.test(target)) {
          return { ok: false, error: "invalid url" };
        }
        try {
          return await openTab(target);
        } catch (e) {
          return { ok: false, error: String(e) };
        }
      case "OPEN_HOME":
        // S2/S6: open the homepage (HOME_URL from /config) in a new tab.
        try {
          return await openTab(CONFIG.homeUrl);
        } catch (e) {
          return { ok: false, error: String(e) };
        }
      case "SWITCH_TAB":
        await chrome.tabs.update(msg.tabId, { active: true });
        return { ok: true };
      case "CLOSE_TAB":
        await chrome.tabs.remove(msg.tabId);
        return { ok: true };
      case "RELAUNCH":
        // POST /restart → supervisorctl restart google-chrome. The restart
        // kills this worker; the response may never arrive — treat any
        // outcome as "request accepted".
        try {
          await fetch(CONFIG.restartUrl, { method: "POST" });
        } catch (_e) {
          /* connection dropped mid-restart is expected */
        }
        return { ok: true, restarting: true };
      case "SELF_RELEASE":
        // Spec 32: tab bar Exit → the slot's restart-api /release → it
        // suspends (snapshot + archive + wipe) and notifies the router
        // with reason=released; the router re-offers the slot to the
        // queue head. The slot-local endpoint derives the user from
        // .slot-user.json, so the release can never target a different
        // owner (same trust shape as RELAUNCH).
        try {
          const r = await fetch("http://127.0.0.1:9230/release", { method: "POST" });
          return { ok: r.ok };
        } catch (e) {
          return { ok: false, error: String(e) };
        }
      case "NAV_BACK": {
        const id = await activeTabId();
        if (id == null) return { ok: false, error: "no active tab" };
        try {
          await chrome.tabs.goBack(id);
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String(e) }; // no history to go back to
        }
      }
      case "NAV_FORWARD": {
        const id = await activeTabId();
        if (id == null) return { ok: false, error: "no active tab" };
        try {
          await chrome.tabs.goForward(id);
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String(e) }; // no forward history
        }
      }
      case "RELOAD_PAGE": {
        const id = await activeTabId();
        if (id == null) return { ok: false, error: "no active tab" };
        try {
          await chrome.tabs.reload(id);
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String(e) };
        }
      }
      default:
        return { ok: false, error: "unknown message" };
    }
  })().then(sendResponse).catch((e) => sendResponse({ ok: false, error: String(e) }));
  return true; // async response
});

// Heal stale content scripts on extension install/update and SW startup.
// Chrome does NOT re-inject content scripts into already-open tabs after an
// extension update; the old script's chrome.runtime bridge then silently
// stops delivering clicks (bar renders, buttons dead, page reload fixes it).
// Probe every tab; re-inject where the script is missing or an older version
// answers. content.js self-guards (versioned window marker) and replaces any
// stale bar it finds, so double injection is safe.
async function healTabs() {
  try {
    const tabs = await chrome.tabs.query({});
    for (const t of tabs) {
      if (!t.id || !t.url) continue;
      if (t.url.startsWith("chrome://") || t.url.startsWith("chrome-extension://")) continue;
      let healthy = false;
      try {
        const r = await chrome.tabs.sendMessage(t.id, { type: "__PING__" });
        healthy = !!(r && r.version === EXT_VERSION);
      } catch (_e) {
        /* no receiver -> (re)inject below */
      }
      if (healthy) continue;
      try {
        await chrome.scripting.executeScript({ target: { tabId: t.id }, files: ["content.js"] });
      } catch (_e) {
        /* restricted origin or frame torn down; next cycle will retry */
      }
    }
  } catch (_e) {
    /* worker shutting down mid-heal; next wake retries */
  }
}
chrome.runtime.onInstalled.addListener(healTabs);
chrome.runtime.onStartup.addListener(healTabs);

// v1.7.0: after config is known, trim any pre-existing excess; the
// onCreated/onUpdated listeners handle everything from then on.
loadConfig().then(() => {
  trimExcess();
});

// --- v1.12.0 (spec O6): error pages get the tab bar ---------------------
// chrome-error://chromewebdata/ cannot be scripted (content scripts and
// chrome.scripting both refuse), so on a failed main-frame navigation we
// REPLACE the tab's error page with our bundled error.html, which shows
// the failure + Retry/Back/Home + a full tab bar (same message protocol
// as content.js, so the SW needs no new handlers).
//
// Pitfalls handled:
// - ERR_ABORTED fires for every user-cancelled / redirected navigation —
//   hijacking those would break normal browsing (downloads, redirects,
//   stop button). Only non-abort errors trigger the replacement.
// - Subframes (frameId !== 0) fail all the time (ads, embeds) — main
//   frame only.
// - Our own error.html is chrome-extension:// → filtered by the
//   http(s) check, so no redirect loop.
chrome.webNavigation.onErrorOccurred.addListener((details) => {
  if (details.frameId !== 0) return; // main frame only
  if (typeof details.tabId !== "number" || details.tabId < 0) return;
  if (details.error === "net::ERR_ABORTED") return; // user stop / redirect
  if (!/^https?:\/\//i.test(details.url)) return; // web targets only
  const target =
    chrome.runtime.getURL("error.html") +
    "?u=" +
    encodeURIComponent(details.url) +
    "&e=" +
    encodeURIComponent(details.error || "net::ERR_FAILED");
  chrome.tabs.update(details.tabId, { url: target }).catch(() => {
    /* tab closed mid-flight */
  });
});
