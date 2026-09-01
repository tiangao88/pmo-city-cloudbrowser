// Cloudbrowser Tab Bar — error page logic (v1.12.0, spec O6 2026-08-22).
// Renders the failed navigation (from ?u= / ?e= query params) and a
// functional tab bar. Talks to background.js with the SAME message
// protocol as content.js (LIST_TABS / SWITCH_TAB / CLOSE_TAB /
// OPEN_HOME / NAV_BACK / NAV_FORWARD / RELOAD_PAGE / RELAUNCH), so the
// service worker needed no new handlers.

(() => {
  const q = new URLSearchParams(location.search);
  const failedUrl = q.get("u") || "";
  const errCode = q.get("e") || "net::ERR_FAILED";

  // Friendly one-liners for the common net::ERR_* codes; anything
  // unknown falls back to the raw code (still greppable in logs).
  const FRIENDLY = {
    "net::ERR_CONNECTION_RESET": "The connection was reset while the page was loading.",
    "net::ERR_CONNECTION_REFUSED": "The site refused the connection.",
    "net::ERR_CONNECTION_CLOSED": "The connection was closed before the page finished loading.",
    "net::ERR_NAME_NOT_RESOLVED": "The server address could not be found (DNS).",
    "net::ERR_NAME_RESOLUTION_FAILED": "The server address could not be found (DNS).",
    "net::ERR_TIMED_OUT": "The connection timed out.",
    "net::ERR_INTERNET_DISCONNECTED": "No internet connection.",
    "net::ERR_SSL_PROTOCOL_ERROR": "The site's security settings blocked the connection.",
    "net::ERR_CERT_COMMON_NAME_INVALID": "The site's security certificate is invalid.",
    "net::ERR_CERT_DATE_INVALID": "The site's security certificate is expired.",
    "net::ERR_CERT_AUTHORITY_INVALID": "The site's security certificate is not trusted.",
    "net::ERR_TOO_MANY_REDIRECTS": "The page redirected too many times.",
    "net::ERR_BLOCKED_BY_CLIENT": "The page was blocked.",
    "net::ERR_EMPTY_RESPONSE": "The server sent no response.",
    "net::ERR_HTTP_RESPONSE_CODE_FAILURE": "The server returned an error response."
  };

  document.getElementById("errUrl").textContent = failedUrl;
  document.getElementById("errCode").textContent =
    FRIENDLY[errCode] || errCode.replace(/^net::/, "net::");

  async function activeTabId() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs.length ? tabs[0].id : null;
  }
  function send(msg) {
    return chrome.runtime.sendMessage(msg).catch(() => ({ ok: false }));
  }

  // Retry: navigate THIS tab back to the failed URL (http/https only —
  // the background listener only ever sends those, but guard anyway).
  document.getElementById("retry").onclick = () => {
    if (/^https?:\/\//i.test(failedUrl)) location.href = failedUrl;
    else location.href = "about:blank";
  };

  // Back: one history step in the active tab. The failing navigation
  // sits in history, so Back leaves the error page.
  document.getElementById("back").onclick = async () => {
    const id = await activeTabId();
    if (id != null) {
      try { await chrome.tabs.goBack(id); } catch (_e) { /* no history */ }
    }
  };

  // Home: same semantics as the content bar — background OPEN_HOME
  // opens HOME_URL (from /config) in a new tab.
  document.getElementById("home").onclick = () => send({ type: "OPEN_HOME" });

  // --- bottom tab bar ---------------------------------------------------
  const elTabs = document.getElementById("tabs");
  let tabs = [];

  function render() {
    elTabs.textContent = "";
    for (const t of tabs) {
      const pill = document.createElement("span");
      pill.className = "tab" + (t.active ? " active" : "");
      pill.title = t.url || "";
      const label = document.createElement("span");
      label.className = "t";
      label.textContent = (t.title || t.url || "tab").slice(0, 80);
      pill.appendChild(label);
      pill.onclick = () => send({ type: "SWITCH_TAB", tabId: t.id });
      if (tabs.length > 1) {
        const x = document.createElement("button");
        x.className = "close";
        x.textContent = "×";
        x.title = "Close tab";
        x.onclick = (e) => {
          e.stopPropagation();
          send({ type: "CLOSE_TAB", tabId: t.id });
        };
        pill.appendChild(x);
      }
      elTabs.appendChild(pill);
    }
  }

  async function refresh() {
    const r = await send({ type: "LIST_TABS" });
    if (r && Array.isArray(r.tabs)) {
      tabs = r.tabs;
      render();
    }
  }

  document.getElementById("bRelaunch").onclick = () => send({ type: "RELAUNCH" });
  document.getElementById("bBack").onclick = async () => {
    const id = await activeTabId();
    if (id != null) {
      try { await chrome.tabs.goBack(id); } catch (_e) { /* noop */ }
    }
  };
  document.getElementById("bFwd").onclick = async () => {
    const id = await activeTabId();
    if (id != null) {
      try { await chrome.tabs.goForward(id); } catch (_e) { /* noop */ }
    }
  };
  document.getElementById("bReload").onclick = async () => {
    const id = await activeTabId();
    if (id != null) {
      try { await chrome.tabs.reload(id); } catch (_e) { /* noop */ }
    }
  };
  document.getElementById("bHome").onclick = () => send({ type: "OPEN_HOME" });

  refresh();
  setInterval(refresh, 1500);
})();
