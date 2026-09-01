// Cloudbrowser Tab Bar — content script (v1.11.0).
// Injects a slim floating tab bar (shadow DOM) into every top-frame page:
//   [« collapse] [▲ pos] [⏻ relaunch] [← back] [→ fwd] [↺ reload] [＋ new]
//   [🔒 Vaultwarden] [📁 Files] | [fav tab] [fav tab] ...
// The ▲ button cycles the bar edge: top → right → bottom → left (clockwise).
// DEFAULT edge = BOTTOM (v1.8.2, Tigo 2026-08-21) — the bar starts at the
// bottom of the screen; the cycle button + stored cbBarPos still override.
// Position state lives in chrome.storage.local ("cbBarPos") so every tab's
// bar moves together; clicks are delegated to the background worker.
//
// v1.2.0 — staleness hardening: versioned marker + self-replacement of stale
// instances (an extension update leaves old content scripts on open tabs with
// a dead chrome.runtime bridge -> clicks silently stop working until reload).
// The background worker re-injects on install/startup; this script replaces
// any older bar it finds and skips when an identical version already runs.
// v1.3.0 — SVG icon set (Lucide paths) + button reorder per Tigo:
// collapse, pos, relaunch, back, fwd, reload, newtab.
// v1.3.1 — position toggle is a filled triangle (▲▶▼◀) per position.
// v1.4.0 — consolidation per Tigo: ＋ newtab + bookmarks (Vaultwarden/Files)
// removed from the bar; it is now pure navigation (collapse, pos, relaunch,
// back, fwd, reload) + tab list. Bookmarks live in the client toolbar.
// v1.5.0 — spec 27 (2026-08-21): bar order becomes collapse, pos, relaunch,
// HOME, back, fwd, reload, PLUS, tabs. HOME opens HOME_URL (from restart-api
// GET /config via the background worker); PLUS opens an inline URL popover
// (http(s) only). TAB_LIMIT (same /config source) gray-out: HOME/PLUS are
// disabled when the real-tab count reaches the limit.
// v1.6.0 — spec 27 S6 (2026-08-21, Tigo): the limit no longer blocks.
// HOME/PLUS stay enabled; the background worker evicts the
// least-recently-used tab instead, and this script shows a toast naming
// the closed tab (TAB_EVICTED message).
// v1.8.0 — spec 29 (2026-08-21): idle-suspend grace countdown. While the
// slot's reaper is in the grace window (restart-api GET /idle →
// status "grace"), this script shows a persistent countdown toast on the
// ACTIVE tab ("Session suspends in ~m:ss — activity cancels"). Polling
// runs only while the document is visible (tab-level idle; hidden tabs
// don't count and don't waste polls).
// v1.8.1 — resilience (2026-08-21): chrome.storage is no longer a
// prerequisite. The default position class is set synchronously at
// injection (bar always visible at top), storage failures are caught
// (no silent promise rejection), and position cycling applies locally
// even when storage is unavailable. Root cause: extension storage
// LevelDB LOCK access denied on root-owned profile volumes left Chrome
// with an invisible bar at the document's static position.
// v1.10.0 — spec 32 (2026-08-22, Tigo): Exit button (right end of the
// bar). One click → confirm popup → background SELF_RELEASE → restart-api
// /release on the slot → router archives the session reason=released and
// re-offers the slot to the queue head; this script then redirects to the
// router origin (queue page). Router origin is cached in
// chrome.storage.local (cbRouterOrigin) whenever the bar runs on a
// cloudbrowser page, so Exit works from external sites too.
// v1.11.0 — spec 41 (2026-08-22, Tigo): Exit button moves OUT of the tab
// bar into the NEKO TOP BAR (right of the email address — user-affordance
// lock from the spec-41 incident review); tab bar no longer hosts Exit.
// Same release flow; the freed slot goes to the queue head, the releaser
// re-queues FIFO (released archives never auto-wake).
// v1.12.0 — spec O6 (2026-08-22): no functional change here — error
// pages (chrome-error://) can't run content scripts, so they get the
// bundled error.html replacement (background webNavigation listener).
// Version bump keeps healTabs' EXT_VERSION probe in sync.
// v1.13.0 — spec 64 (2026-08-25, Tigo): universal Exit FALLBACK. The
// neko top bar (ul.menu) only exists on cloudbrowser pages, so external
// tabs (Vaultwarden/CloudFiles/SSO) had no release affordance. This
// version re-adds the bar Exit button, shown ONLY when no neko top bar
// is present (spec 41 keeps the top-bar exit primary on cloudbrowser
// pages). Same confirm popup → SELF_RELEASE → /release flow.

(() => {
  const VERSION = "1.14.0";
  if (window.__cbTabBar === VERSION) return; // fresh instance already active
  const staleHost = document.querySelector('div[style*="2147483647"]');
  if (staleHost) staleHost.remove(); // supersede an older bar instance
  window.__cbTabBar = VERSION;

  const POLL_MS = 1500;
  const POSITIONS = ["top", "right", "bottom", "left"];
  const POS_GLYPH = { top: "▲", right: "▶", bottom: "▼", left: "◀" };

  const host = document.createElement("div");
  host.dataset.cbVersion = VERSION; // main-world-visible marker for diagnostics
  host.style.cssText =
    "position:fixed;z-index:2147483647;font-family:system-ui,sans-serif;";
  // v1.8.1 — resilience (2026-08-21): set the DEFAULT position class
  // synchronously so the bar is never stranded at its static document
  // position (y = page height, invisible) when chrome.storage rejects
  // (e.g. extension LevelDB LOCK access denied after a profile-ownership
  // breakage). Storage refines the position; it is no longer a
  // prerequisite for visibility.
  host.className = "cb-pos-bottom";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
<style>
  :host { all: initial; display: block; position: fixed; z-index: 2147483647; font-family: system-ui, sans-serif; }
  :host(.cb-pos-top) { top: 0; left: 0; right: 0; height: 26px; }
  :host(.cb-pos-bottom) { bottom: 0; left: 0; right: 0; height: 26px; }
  :host(.cb-pos-left) { top: 0; left: 0; bottom: 0; width: 178px; }
  :host(.cb-pos-right) { top: 0; right: 0; bottom: 0; width: 178px; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  #bar {
    display: flex; align-items: center; gap: 6px; height: 100%;
    background: rgba(17,17,19,.92); color: #e8e8ea; font-size: 12px;
    padding: 0 8px; user-select: none; cursor: default; white-space: nowrap;
  }
  :host(.cb-pos-top) #bar { flex-direction: row; border-bottom: 1px solid rgba(255,255,255,.08); }
  :host(.cb-pos-bottom) #bar { flex-direction: row; border-top: 1px solid rgba(255,255,255,.08); }
  :host(.cb-pos-left) #bar, :host(.cb-pos-right) #bar {
    flex-direction: column; align-items: stretch; padding: 8px; white-space: normal;
  }
  #bar.collapsed { height: 18px; justify-content: flex-start; }
  :host(.cb-pos-left) #bar.collapsed, :host(.cb-pos-right) #bar.collapsed { width: 18px; height: 100%; padding: 4px 2px; }
  #bar.collapsed #tabs, #bar.collapsed .act { display: none; }
  button {
    display: inline-flex; align-items: center; justify-content: center;
    background: rgba(255,255,255,.09); color: #e8e8ea; border: 0; border-radius: 5px;
    font-size: 12px; line-height: 16px; padding: 3px 7px; cursor: pointer; flex: none;
  }
  button svg { display: block; }
  button:hover { background: rgba(255,255,255,.22); }
  #tabs { display: flex; gap: 4px; flex: 1; overflow: hidden; min-width: 0; }
  :host(.cb-pos-left) #tabs, :host(.cb-pos-right) #tabs {
    flex-direction: column; overflow-y: auto; flex: 1 1 auto; min-height: 0; align-self: stretch;
  }
  .tab {
    display: inline-flex; align-items: center; gap: 5px; max-width: 170px;
    background: rgba(255,255,255,.06); border-radius: 4px; padding: 1px 4px 1px 6px;
    cursor: pointer; overflow: hidden;
  }
  :host(.cb-pos-left) .tab, :host(.cb-pos-right) .tab { max-width: 100%; }
  .tab.active { background: rgba(255,255,255,.28); outline: 1px solid rgba(255,255,255,.35); }
  .tab img { width: 12px; height: 12px; flex: none; margin-right: 6px; }
  .tab .t { overflow: hidden; text-overflow: ellipsis; }
  .tab .x { border: 0; background: transparent; color: #9aa; padding: 0 2px; font-size: 11px; cursor: pointer; flex: none; }
  .tab .x:hover { color: #fff; }
  .act { flex: none; }
  #collapse { flex: none; width: 18px; padding: 0; text-align: center; }
  button:disabled { opacity: .35; cursor: default; }
  #toast {
    position: fixed; bottom: 34px; left: 50%; transform: translateX(-50%);
    background: rgba(30,30,34,.95); color: #ffd9a0;
    border: 1px solid rgba(255,255,255,.15); border-radius: 6px;
    padding: 6px 12px; font-size: 12px; max-width: 70vw;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    box-shadow: 0 2px 8px rgba(0,0,0,.4);
  }
  #urlpop, #exitpop {
    position: fixed; z-index: 2147483647; display: flex; align-items: center; gap: 6px;
    background: rgba(28,28,32,.97); border: 1px solid rgba(255,255,255,.16); border-radius: 6px;
    padding: 6px 8px; font-size: 12px; color: #e8e8ea; box-shadow: 0 4px 16px rgba(0,0,0,.5);
  }
  #urlpop[hidden], #exitpop[hidden] { display: none; }
  #exitpop { flex-wrap: wrap; max-width: 330px; }
  #exitpop-txt { flex-basis: 100%; padding: 2px 2px 6px; line-height: 1.35; }
  #urlpop input {
    width: 230px; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.2);
    border-radius: 4px; color: #e8e8ea; padding: 3px 7px; font-size: 12px; outline: none; flex: none;
  }
  #urlpop input:focus { border-color: #8DD3B1; }
  #urlpop button { padding: 3px 10px; }
  #urlpop-err { color: #ff9d9d; font-size: 11px; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
<div id="bar">
  <button id="collapse" title="Collapse bar"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/></svg></button>
  <button class="act" id="pos" title="Bar position: top (click to cycle)"></button>
  <button class="act" id="relaunch" title="Relaunch Chrome"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/></svg></button>
  <button class="act" id="home" title="Home"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg></button>
  <button class="act" id="back" title="Back"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg></button>
  <button class="act" id="fwd" title="Forward"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></button>
  <button class="act" id="reload" title="Reload page"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg></button>
  <button class="act" id="plus" title="Open URL"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg></button>
  <div id="tabs"></div>
</div>
<div id="urlpop" hidden>
  <span id="urlpop-err"></span>
  <input id="urlpop-in" type="text" placeholder="https://…" spellcheck="false"/>
  <button id="urlpop-ok">OK</button>
  <button id="urlpop-cancel">Cancel</button>
</div>
<div id="exitpop" hidden>
  <span id="exitpop-txt">Release this slot? Your session is archived and the next person in queue gets the browser.</span>
  <button id="exitpop-ok">Release slot</button>
  <button id="exitpop-cancel">Cancel</button>
</div>
`;

  const bar = root.getElementById("bar");
  const tabsEl = root.getElementById("tabs");
  const collapseBtn = root.getElementById("collapse");
  const relaunchBtn = root.getElementById("relaunch");
  const posBtn = root.getElementById("pos");
  const homeBtn = root.getElementById("home");
  const backBtn = root.getElementById("back");
  const fwdBtn = root.getElementById("fwd");
  const reloadBtn = root.getElementById("reload");
  const plusBtn = root.getElementById("plus");
  const urlpop = root.getElementById("urlpop");
  const urlpopErr = root.getElementById("urlpop-err");
  const urlpopIn = root.getElementById("urlpop-in");
  const urlpopOk = root.getElementById("urlpop-ok");
  const urlpopCancel = root.getElementById("urlpop-cancel");

  // S4/S6: tab limit state (values come from LIST_TABS -> background /config).
  // v1.6.0: informational tooltip only — HOME/PLUS are never disabled; the
  // background worker evicts the least-recently-used tab at the limit.
  let tabLimit = null;
  let numTabs = 0;
  function applyLimit() {
    const at = tabLimit != null && numTabs >= tabLimit;
    homeBtn.disabled = plusBtn.disabled = false;
    const tip = at ? "Limit " + tabLimit + " — closes least-used tab" : "";
    homeBtn.title = tip || "Home";
    plusBtn.title = tip || "Open URL";
  }

  // v1.6.0: eviction toast — briefly names the tab closed by LRU eviction.
  const toastEl = document.createElement("div");
  toastEl.id = "toast";
  toastEl.hidden = true;
  root.appendChild(toastEl);
  let toastTimer = null;
  function showToast(text) {
    toastEl.textContent = text;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastEl.hidden = true;
    }, 4500);
  }
  try {
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg && msg.type === "TAB_EVICTED" && msg.title) {
        showToast("Tab closed (limit " + (tabLimit ?? "?") + "): " + String(msg.title).slice(0, 60));
      }
    });
  } catch (_e) { /* v1.8.1: runtime bridge unavailable — eviction toasts only */ }

  // v1.8.0 — idle-suspend grace countdown (spec 29). Persistent toast while
  // restart-api reports status "grace"; hidden on active/suspended. Poll
  // only on the visible tab; a hidden tab's bar must not stack toasts.
  let idleToastVisible = false;
  function showIdleToast(text) {
    idleToastVisible = true;
    toastEl.textContent = text;
    toastEl.hidden = false;
    clearTimeout(toastTimer); // persistent — no auto-hide
  }
  function hideIdleToast() {
    if (!idleToastVisible) return;
    idleToastVisible = false;
    toastEl.hidden = true;
    clearTimeout(toastTimer);
  }
  function fmtCountdown(secs) {
    const m = Math.floor(secs / 60), s = secs % 60;
    return m + ":" + String(s).padStart(2, "0");
  }
  async function pollIdle() {
    if (document.visibilityState !== "visible") return;
    try {
      const r = await fetch("http://127.0.0.1:9230/idle", { cache: "no-store" });
      if (!r.ok) { hideIdleToast(); return; }
      const st = await r.json();
      if (st.status === "grace" && st.secondsLeft > 0) {
        showIdleToast("Session suspends in ~" + fmtCountdown(st.secondsLeft) + " — activity cancels");
      } else {
        hideIdleToast();
      }
    } catch (_e) {
      hideIdleToast(); // restart-api down — nothing to warn about
    }
  }
  setInterval(pollIdle, 15000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") pollIdle();
  });

  let collapsed = false;
  try { collapsed = localStorage.getItem("cb_tabbar_collapsed") === "1"; } catch (_e) {}
  if (collapsed) bar.classList.add("collapsed");

  const POS_ICON = {
    top: '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="m12 5 7 14H5z"/></svg>',
    right: '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M19 12 5 19V5z"/></svg>',
    bottom: '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="m12 19 5-14H7z"/></svg>',
    left: '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M5 12 19 5v14z"/></svg>'
  };
  const SPINNER = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>';
  const POWER_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/></svg>';

  let pos = "bottom";
  function applyPos(p) {
    pos = POSITIONS.includes(p) ? p : "bottom";
    host.className = "cb-pos-" + pos;
    posBtn.innerHTML = POS_ICON[pos];
    posBtn.title = "Bar position: " + pos + " (click to cycle)";
  }
  function cyclePos() {
    const next = POSITIONS[(POSITIONS.indexOf(pos) + 1) % POSITIONS.length];
    applyPos(next); // v1.8.1: apply locally first — storage may reject
    try {
      chrome.storage.local.set({ cbBarPos: next }); // onChanged applies it everywhere
    } catch (_e) { /* storage unavailable — this tab keeps the new position */ }
  }
  applyPos("bottom"); // v1.8.2: default = bottom (Tigo); storage refines below
  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.cbBarPos) applyPos(changes.cbBarPos.newValue);
    });
    chrome.storage.local.get("cbBarPos")
      .then((v) => applyPos(v.cbBarPos))
      .catch(() => { /* storage rejected — bar stays at the default position */ });
  } catch (_e) { /* storage unavailable — bar stays at the default position */ }

  // Ping handler: the background worker probes open tabs on install/startup
  // to find stale instances and re-inject. Answer with our version.
  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (msg && msg.type === "__PING__") sendResponse({ version: VERSION });
  });

  // Hardened messaging: retries transient SW cold-start races, never throws.
  function send(msg, tries = 0) {
    return new Promise((resolve) => {
      const done = (r) => resolve(r || { ok: false });
      try {
        chrome.runtime.sendMessage(msg, (r) => {
          if (chrome.runtime.lastError) {
            if (tries < 2) setTimeout(() => send(msg, tries + 1).then(done), 400);
            else done({ ok: false, error: String(chrome.runtime.lastError.message) });
            return;
          }
          done(r);
        });
      } catch (e) {
        if (tries < 2) setTimeout(() => send(msg, tries + 1).then(done), 400);
        else done({ ok: false, error: String(e) });
      }
    });
  }

  function render(tabs) {
    tabsEl.textContent = "";
    numTabs = tabs.length;
    if (!tabs.length) { applyLimit(); return; }
    const single = tabs.length === 1;
    tabs.forEach((t) => {
      const el = document.createElement("div");
      el.className = "tab" + (t.active ? " active" : "");
      el.title = t.url;
      if (t.favIconUrl) {
        const img = document.createElement("img");
        img.src = t.favIconUrl;
        img.onerror = () => img.remove();
        el.appendChild(img);
      }
      const span = document.createElement("span");
      span.className = "t";
      span.textContent = t.title || t.url;
      el.appendChild(span);
      if (!single) {
        const x = document.createElement("button");
        x.className = "x";
        x.textContent = "×";
        x.addEventListener("click", (e) => {
          e.stopPropagation();
          send({ type: "CLOSE_TAB", tabId: t.id });
        });
        el.appendChild(x);
      }
      el.addEventListener("click", () => send({ type: "SWITCH_TAB", tabId: t.id }));
      tabsEl.appendChild(el);
    });
    applyLimit();
  }

  async function refresh() {
    const r = await send({ type: "LIST_TABS" });
    if (!r || !r.tabs) return;
    if (Number.isInteger(r.tabLimit) && r.tabLimit > 0) tabLimit = r.tabLimit;
    render(r.tabs);
  }

  // S3: inline URL popover (anchored to the ＋ button).
  function openPopover() {
    const rect = plusBtn.getBoundingClientRect();
    urlpopErr.textContent = "";
    urlpopIn.value = "";
    urlpop.hidden = false;
    if (pos === "bottom") {
      urlpop.style.top = (rect.top - 44) + "px";
      urlpop.style.left = Math.max(4, rect.left) + "px";
    } else if (pos === "left") {
      urlpop.style.top = rect.top + "px";
      urlpop.style.left = (rect.right + 6) + "px";
    } else if (pos === "right") {
      urlpop.style.top = rect.top + "px";
      urlpop.style.left = Math.max(4, rect.left - urlpop.offsetWidth - 6) + "px";
    } else {
      urlpop.style.top = (rect.bottom + 4) + "px";
      urlpop.style.left = Math.max(4, rect.left) + "px";
    }
    urlpopIn.focus();
  }
  function closePopover() {
    urlpop.hidden = true;
    urlpopErr.textContent = "";
  }
  function submitUrl() {
    const v = urlpopIn.value.trim();
    if (!v) { closePopover(); return; }
    send({ type: "OPEN_URL", url: v }).then((r) => {
      if (r && r.ok) {
        closePopover(); refresh();
        if (r.evictedTitle) showToast("Tab closed (limit " + (tabLimit ?? "?") + "): " + String(r.evictedTitle).slice(0, 60));
      }
      else { urlpopErr.textContent = (r && r.error) ? r.error : "Could not open URL"; }
    });
  }

  collapseBtn.addEventListener("click", () => {
    collapsed = !collapsed;
    bar.classList.toggle("collapsed", collapsed);
    try { localStorage.setItem("cb_tabbar_collapsed", collapsed ? "1" : "0"); } catch (_e) {}
  });
  backBtn.addEventListener("click", () => send({ type: "NAV_BACK" }));
  fwdBtn.addEventListener("click", () => send({ type: "NAV_FORWARD" }));
  reloadBtn.addEventListener("click", () => send({ type: "RELOAD_PAGE" }));
  posBtn.addEventListener("click", cyclePos);
  relaunchBtn.addEventListener("click", () => {
    relaunchBtn.innerHTML = SPINNER;
    send({ type: "RELAUNCH" }).then(() => setTimeout(() => (relaunchBtn.innerHTML = POWER_ICON), 3000));
  });
  homeBtn.addEventListener("click", () => {
    if (homeBtn.disabled) return; // never disabled since v1.6.0 — kept as guard
    send({ type: "OPEN_HOME" }).then((r) => {
      if (r && r.ok && r.evictedTitle) {
        showToast("Tab closed (limit " + (tabLimit ?? "?") + "): " + String(r.evictedTitle).slice(0, 60));
      }
    });
  });
  // v1.14.0 (spec 68, Tigo 2026-08-25): the spec-64 tab-bar Exit FALLBACK
  // is REMOVED. The neko top-bar Exit (ensureBarExit, spec 41) is the only
  // release affordance — Tigo: bottom-right exit icon is wrong; the
  // top-right Exit session button is the good one.

  plusBtn.addEventListener("click", () => {
    if (plusBtn.disabled) return; // S4
    openPopover();
  });
  urlpopOk.addEventListener("click", submitUrl);
  urlpopCancel.addEventListener("click", closePopover);
  urlpopIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitUrl();
    else if (e.key === "Escape") closePopover();
  });

  // Spec 32/41: Exit (slot release). Spec 41 (2026-08-22, Tigo): the button
  // lives in the NEKO TOP BAR, right of the email address — NOT the tab bar.
  // Same flow: confirm popup → SELF_RELEASE → restart-api /release → router
  // archives reason=released and offers the slot to the queue head.
  const exitpop = root.getElementById("exitpop");
  const exitpopOk = root.getElementById("exitpop-ok");
  const exitpopCancel = root.getElementById("exitpop-cancel");
  let barExitBtn = null; // the neko-bar button (page DOM, not shadow)
  function openExitPop() {
    const anchor = barExitBtn;
    if (!anchor) return;
    exitpop.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const w = exitpop.offsetWidth || 330;
    const h = exitpop.offsetHeight || 88;
    // v1.13.1 (spec 64): anchor by bar position. The neko top bar sits at
    // the TOP (popup below); the tab-bar fallback can sit at the BOTTOM
    // (popup ABOVE, or it rendered off-screen below the viewport and the
    // Release confirm was invisible — Tigo 2026-08-25).
    if (pos === "bottom") {
      exitpop.style.top = Math.max(4, rect.top - h - 4) + "px";
    } else {
      exitpop.style.top = (rect.bottom + 4) + "px";
    }
    exitpop.style.left = Math.max(
      4, Math.min(rect.right - w, window.innerWidth - w - 4)) + "px";
  }
  function closeExitPop() {
    exitpop.hidden = true;
    exitpopOk.disabled = false;
    exitpopOk.textContent = "Release slot";
  }
  exitpopCancel.addEventListener("click", closeExitPop);
  exitpopOk.addEventListener("click", () => {
    exitpopOk.disabled = true;
    exitpopOk.textContent = "Releasing…";
    send({ type: "SELF_RELEASE" }).then((r) => {
      if (r && r.ok) {
        showToast("Slot released — you are back in the queue");
        chrome.storage.local.get("cbRouterOrigin", (o) => {
          const origin = (o && o.cbRouterOrigin) || "https://cloudbrowser.dev01.pmo.city";
          location.href = origin + "/";
        });
      } else {
        exitpopOk.disabled = false;
        exitpopOk.textContent = "Release slot";
        showToast("Release failed: " + ((r && r.error) || "unknown error"));
      }
    });
  });

  // Spec 41: inject the Exit button into the neko top bar (ul.menu), right
  // of the email pill (.cb-email-li is the rightmost element). The bar is
  // router/title-proxy injected on the session + landing + queue pages; the
  // queue page is excluded via /fleet/my-status (state != active → no
  // button). Re-injected if the bar re-renders (neko Vue / title-proxy ap()).
  const EXIT_SVG = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>';
  function ensureBarExit() {
    const m = document.querySelector("ul.menu");
    if (!m || m.querySelector(".cb-exit-li")) return;
    fetch("/fleet/my-status", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((st) => {
        if (!st || st.state !== "active") return; // queue page etc.
        const mm = document.querySelector("ul.menu");
        if (!mm || mm.querySelector(".cb-exit-li")) return;
        const li = document.createElement("li");
        li.className = "cb-exit-li";
        li.style.cssText = "display:inline-flex;align-items:center;margin-left:10px;list-style:none;";
        const btn = document.createElement("button");
        btn.type = "button";
        btn.title = "Exit and release slot";
        btn.innerHTML = EXIT_SVG;
        btn.style.cssText = "display:inline-flex;align-items:center;justify-content:center;width:24px;height:22px;padding:0;border:none;border-radius:4px;background:rgba(255,255,255,.08);color:#f0a0a0;cursor:pointer;";
        btn.addEventListener("mouseover", () => { btn.style.background = "rgba(255,255,255,.2)"; btn.style.color = "#ff6b6b"; });
        btn.addEventListener("mouseout", () => { btn.style.background = "rgba(255,255,255,.08)"; btn.style.color = "#f0a0a0"; });
        btn.addEventListener("click", openExitPop);
        li.appendChild(btn);
        barExitBtn = btn;
        const emailLi = mm.querySelector(".cb-email-li");
        if (emailLi) emailLi.insertAdjacentElement("afterend", li);
        else mm.appendChild(li);
      })
      .catch(() => {});
  }
  ensureBarExit();
  new MutationObserver(() => {
    if (!document.querySelector("ul.menu .cb-exit-li")) {
      barExitBtn = null;
      ensureBarExit();
    }
  }).observe(document.body || document.documentElement,
             { childList: true, subtree: true });

  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });

  (document.body || document.documentElement).appendChild(host);
  refresh();
  setInterval(refresh, POLL_MS);
})();

// =====================================================================
// Session watchdog (v1.9.0, 2026-08-22, Tigo A+B) — never stuck on the
// neko LOG IN screen again.
//
// The router injects an equivalent in-page watchdog, but only when its
// index fetch succeeds; pages already open (or served via the raw-proxy
// fallback) never get it. THIS watchdog lives in the extension, which
// runs on EVERY http(s) page — including the neko LOG IN screen (proven
// by Tigo's screenshot: the top bar renders there). Same contract as the
// in-page watchdog:
//   /fleet/my-status → state != "active" → location = "/" (queue/landing)
//   state == active but neko LOG IN visible → re-enter via open_url
//     (dropped viewer WebSocket; neko strips pwd/usr after auto-login,
//     so the redirect cannot loop).
// Gate: only on pages where the neko app shell exists (<neko-connect>
// custom element) AND the host is the router origin — the queue page,
// landing page and arbitrary sites never bounce. Same-origin fetch
// (tinyauth adds Remote-Email), so no CORS needed.
(function () {
  try {
    var host = location.hostname.toLowerCase();
    if (host.indexOf("cloudbrowser") !== 0 && host.indexOf("localhost") !== 0) return;
    // Spec 32: remember the router origin — the Exit button redirects
    // there after releasing the slot (also when clicked on external sites).
    try {
      chrome.storage.local.set({ cbRouterOrigin: location.origin });
    } catch (_e) {}
    var MS = 2000;
    function loginScreen() {
      var el = document.querySelector("neko-connect");
      if (!el) return false;
      var r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    }
    setInterval(function () {
      if (!document.querySelector("neko-connect")) return; // not neko app
      fetch("/fleet/my-status", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.state) return;
          if (d.state !== "active") { location.href = "/"; return; }
          if (loginScreen() && location.search.indexOf("pwd=") === -1) {
            fetch("/queue/status", { cache: "no-store" })
              .then(function (r) { return r.json(); })
              .then(function (j) {
                if (j && j.status === "active" && j.open_url) {
                  location.href = j.open_url;
                }
              })
              .catch(function () {});
          }
        })
        .catch(function () {});
    }, MS);
  } catch (e) {}
})();
