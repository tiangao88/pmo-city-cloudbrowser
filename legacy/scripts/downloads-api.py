#!/usr/bin/env python3
"""D8 — in-viewer downloads file list + retrieval (FR-12 I1, W2 build).

Serves the per-user download area (/data/downloads) to BOTH surfaces:
  - viewer: the user opens http://127.0.0.1:9231/ inside the viewer Chrome
    (kiosk: agent opens it on request — "open my downloads");
  - agent: GET /api/files (JSON) and GET /dl/<name> (bytes).

Top bar (2026-08-20, Tigo): mirrors the Cloud Browser toolbar — PMO logo +
"Cloud Files" wordmark on the left; on the right the dynamic email
(Remote-Email, appended by tinyauth), a 🔒 Secrets pill and a 🌐 Cloud
Browser pill (opens the browser surface in a new tab). No neko control
icons (mouse/lock/burger) — this is not neko's UI. URLs come from env so
the template mirror stays scrubbed (placeholders below).

Endpoints:
  GET /           → HTML page, auto-refreshing (fetch /api/files every 3 s)
  GET /api/files  → [{name, size, mtime, quarantined, qname}]
  GET /file/<name> → attachment bytes (nothing renders inline in the
                   embedded browser — download-only, see §30)
  GET /dl/<name>  → Content-Disposition attachment (lands back in the area)
  GET /health     → {"ok": true}

Path safety: names are url-unquoted + basename'd; dotfiles are never served
(quarantine entries are surfaced via /api/files with quarantined: true, shown
in their own section). Pure stdlib — survives container recreates.

Env: DOWNLOADS_DIR (default /home/neko/Downloads), PORT (default 9231),
BROWSER_URL (default https://cloudbrowser.example.invalid/),
SECRETS_URL (default https://vaultwarden.example.invalid/),
SESSIONS_DIR (default /data/sessions).

Per-user isolation (2026-08-22, Tigo: "CloudFiles is not isolated per
user"): every request is resolved to the REQUESTER's own area via the
Remote-Email header:
  - email == the slot's current user (.slot-user.json) → the LIVE
    slot dir (their restored Downloads — new downloads land here);
  - email has a per-user archive (/data/sessions/<email>/Downloads) →
    their OWN archived area (read-only view of their last session);
  - otherwise → empty listing (no cross-user visibility, ever).
The router may send any user to any slot (its CloudFiles fallback is
slot-1 for unassigned users); this layer makes that harmless.
"""
from __future__ import annotations

import base64
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# PMO City brand mark (from https://pmo.city/ navbar, 2026-08-22) — favicon
# for CloudFiles (Tigo: "for all pages the favicon should be the PMO City
# logo and not the Neko cat").
_PMO_LOGO = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 470">'
             '<path fill-rule="evenodd" fill="#3D6475" '
             'd="M 60,235 A 190,190 0 1,0 440,235 A 190,190 0 1,0 60,235 Z '
             'M 118,235 A 132,132 0 1,1 382,235 A 132,132 0 1,1 118,235 Z"/>'
             '<rect x="22" y="210" width="456" height="50" fill="#3D6475"/>'
             '<circle cx="250" cy="235" r="72" fill="#6DD5B5"/></svg>')
FAVICON_B64 = base64.b64encode(_PMO_LOGO.encode("utf-8")).decode("ascii")

DOWNLOADS = os.environ.get("DOWNLOADS_DIR", "/home/neko/Downloads")
PORT = int(os.environ.get("PORT", "9231"))
SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "/data/sessions")
SLOT_USER_FILE = os.path.join(DOWNLOADS, ".slot-user.json")
QUARANTINE = os.path.join(DOWNLOADS, ".quarantine")
BROWSER_URL = os.environ.get("BROWSER_URL", "https://cloudbrowser.example.invalid/")
SECRETS_URL = os.environ.get("SECRETS_URL", "https://vaultwarden.example.invalid/")
# Spec 37: GrantHub "Shared" pill. GRANTHUB_STATUS_URL optional JSON
# endpoint {"shared": bool} keyed by Remote-Email; unset/unreachable →
# "Not Shared" (never a false green).
GRANTHUB_URL = os.environ.get("GRANTHUB_URL", "https://cloudbrowser.dev01.pmo.city/connect")
GRANTHUB_STATUS_URL = os.environ.get("GRANTHUB_STATUS_URL", "")


def _shared_state(email: str) -> tuple:
    """Return (label, css_class) for the GrantHub Shared pill."""
    if GRANTHUB_STATUS_URL:
        try:
            req = urllib.request.Request(
                GRANTHUB_STATUS_URL,
                headers={"Remote-Email": email, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                if json.loads(r.read().decode("utf-8", "replace")).get("shared"):
                    return ("🔗 Shared", "cb-shared")
        except Exception:
            pass
    return ("🔗 Not Shared", "cb-noshared")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def safe_name(raw: str) -> str | None:
    """Return a safe basename for /file and /dl routes, or None."""
    name = urllib.parse.unquote(raw)
    name = os.path.basename(name.replace("\\", "/"))
    if not name or name.startswith(".") or name in ("", ".."):
        return None
    if "/" in name or "\x00" in name:
        return None
    return name


def resolve_area(email: str) -> tuple:
    """Return (area_dir, quarantine_dir, is_live) for the REQUESTER.

    - email == slot's current user → live slot Downloads (writable).
    - email has a per-user archive → their archived Downloads (read-only).
    - anything else → (None, None, False): empty area, no cross-user view.
    """
    email = (email or "").strip()
    try:
        with open(SLOT_USER_FILE) as f:
            slot_user = json.load(f).get("user", "")
    except Exception:
        slot_user = ""
    if email and email == slot_user:
        return DOWNLOADS, os.path.join(DOWNLOADS, ".quarantine"), True
    if email:
        arch = os.path.join(SESSIONS_DIR, email, "Downloads")
        if os.path.isdir(arch):
            return arch, os.path.join(arch, ".quarantine"), False
    return None, None, False


def list_files_for(email: str) -> list:
    """Requester-scoped flat area + quarantine entries, newest first."""
    area, qdir, _ = resolve_area(email)
    out = []
    if area is None:
        return out
    try:
        for name in os.listdir(area):
            p = os.path.join(area, name)
            if name.startswith(".") or not os.path.isfile(p):
                continue
            st = os.stat(p)
            out.append({"name": name, "size": st.st_size,
                        "mtime": int(st.st_mtime), "quarantined": False})
    except OSError as e:
        print(f"[downloads-api] list {area}: {e}", flush=True)
    # quarantine entries (surfaced, never served)
    try:
        for name in sorted(os.listdir(qdir or "")):
            p = os.path.join(qdir, name)
            if not os.path.isfile(p):
                continue
            st = os.stat(p)
            # .quarantine/<ts>_<original>
            qname = name.split("_", 1)[1] if "_" in name else name
            out.append({"name": qname, "size": st.st_size,
                        "mtime": int(st.st_mtime), "quarantined": True,
                        "qname": name})
    except OSError:
        pass
    out.sort(key=lambda f: f["mtime"], reverse=True)
    return out


# %(TITLE)s / %(EMAIL_SPAN)s / %(SECRETS_URL)s / %(BROWSER_URL)s are filled
# per-request by the handler; literal % must stay doubled (%%).
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>%(TITLE)s</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,%(FAVICON_B64)s">
<style>
 body{background:#12141a;color:#e8eaf0;font-family:system-ui,sans-serif;margin:0}
 /* top bar — mirrors Cloud Browser toolbar (neko header: 40px, #202225) */
 .cb-bar{display:flex;align-items:center;justify-content:space-between;gap:16px;
   height:40px;padding:0 20px;background:#202225;position:sticky;top:0;z-index:5}
 .cb-brand{display:flex;align-items:center;gap:10px;min-width:0}
 .cb-logo{width:30px;height:30px;flex:none;display:block}
 .cb-word{font-size:30px;line-height:30px;font-family:Whitney,'Helvetica Neue',Helvetica,Arial,sans-serif;
   color:#dcddde;white-space:nowrap}
 .cb-word b{font-weight:900}
 .cb-actions{display:flex;align-items:center;gap:10px;min-width:0}
 .cb-email{font-size:13px;font-weight:500;color:rgba(255,255,255,.72);
   letter-spacing:.2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .cb-pill{font-size:12px;font-weight:500;color:#c9cdd8;background:rgba(255,255,255,.08);
   padding:3px 9px;border-radius:4px;text-decoration:none;white-space:nowrap;
   display:inline-flex;align-items:center}
 .cb-pill:hover{background:rgba(255,255,255,.2);color:#fff}
 .cb-pill.cb-shared{color:#22c55e}
 .cb-pill.cb-noshared{color:#ef4444}
 .cb-sep{display:block;width:1px;height:14px;background:rgba(255,255,255,.15);margin:0 6px}
 h1{font-size:20px;padding:18px 24px 6px;margin:0}
 .sub{color:#8b93a7;font-size:12px;padding:0 24px 14px}
 table{width:100%%;border-collapse:collapse;font-size:14px}
 th{text-align:left;color:#8b93a7;font-weight:500;font-size:12px;
    padding:6px 24px;border-bottom:1px solid #232839;position:sticky;top:40px;background:#12141a}
 td{padding:8px 24px;border-bottom:1px solid #1b2030}
 a{color:#7aa2ff;text-decoration:none} a:hover{text-decoration:underline}
 .q{color:#ffb454} .q a{color:#ff7a7a}
 .size{color:#8b93a7;font-variant-numeric:tabular-nums;white-space:nowrap}
 .date{color:#5d657a;font-variant-numeric:tabular-nums;white-space:nowrap}
 .empty{color:#5d657a;padding:40px 24px;text-align:center}
 .badge{display:inline-block;background:#3a2a12;color:#ffb454;border-radius:4px;
        font-size:11px;padding:1px 7px;margin-left:8px}
 .badgeq{background:#3a1515;color:#ff7a7a}
 #err{color:#ff7a7a;padding:8px 24px;display:none}
</style></head><body>
<header class="cb-bar">
  <div class="cb-brand">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" class="cb-logo" aria-hidden="true"><rect x="0" y="44.3" width="100" height="11.4" fill="#404E5B"/><circle cx="50" cy="50" r="37.9" fill="none" stroke="#404E5B" stroke-width="11.4"/><circle cx="50" cy="50" r="15.2" fill="#8DD3B1"/></svg>
    <span class="cb-word"><b>C</b>loud<b>F</b>iles</span>
  </div>
  <div class="cb-actions"><a class="cb-pill" href="%(BROWSER_URL)s" target="_blank" rel="noopener">🌐&nbsp;<b>C</b>loud<b>B</b>rowser</a><span class="cb-sep"></span><a class="cb-pill" href="%(SECRETS_URL)s" target="_blank" rel="noopener">🔒 Secrets</a><span class="cb-sep"></span>%(EMAIL_SPAN)s</div>
</header>
<h1>📁 My downloads</h1>
<div class="sub">flat per-user area · 5 GB / 90 days · scanned by ClamAV at ingest ·
refreshes automatically</div>
<div id="err"></div>
<table><thead><tr><th>File</th><th>Size</th><th>Date</th><th></th></tr></thead>
<tbody id="rows"></tbody></table>
<div id="empty" class="empty" style="display:none">No files yet.</div>
<script>
async function refresh(){
  try{
    const r=await fetch('/api/files'); const f=await r.json();
    document.getElementById('err').style.display='none';
    const tb=document.getElementById('rows'); tb.innerHTML='';
    if(!f.length){document.getElementById('empty').style.display='block';return}
    document.getElementById('empty').style.display='none';
    for(const x of f){
      const tr=document.createElement('tr');
      const d=new Date(x.mtime*1000).toLocaleString();
      const sz=x.quarantined?x.size+' <span class="badge badgeq">quarantined (ClamAV)</span>':
        human(x.size);
      let actions='';
      if(!x.quarantined){
        actions='<a href="/dl/'+encodeURIComponent(x.name)+'">download</a>';
      } else {
        actions='<span class="q">ask the agent to inspect</span>';
      }
      tr.innerHTML='<td><a href="/dl/'+encodeURIComponent(x.name)+'">'+
        esc(x.name)+'</a></td><td class="size">'+sz+'</td>'+
        '<td class="date">'+d+'</td><td>'+actions+'</td>';
      tb.appendChild(tr);
    }
  }catch(e){
    document.getElementById('err').style.display='block';
    document.getElementById('err').textContent='connection lost — retrying…';
  }
}
function human(n){const u=['B','KB','MB','GB'];let i=0;while(n>=1024&&i<3){n/=1024;i++}
  return (i===0?n+' B':n.toFixed(1)+' '+u[i])}
function esc(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
refresh(); setInterval(refresh,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, name: str, email: str):
        """Always Content-Disposition: attachment — nothing renders inline
        in the embedded browser (Tigo 2026-08-22, download-only rule)."""
        fn = safe_name(name)
        if fn is None:
            self._send(400, b'{"error":"bad name"}')
            return
        area, _, _ = resolve_area(email)
        if area is None:
            self._send(404, b'{"error":"not found"}')
            return
        p = os.path.join(area, fn)
        try:
            st = os.stat(p)
        except OSError:
            self._send(404, b'{"error":"not found"}')
            return
        if not os.path.isfile(p):
            self._send(404, b'{"error":"not found"}')
            return
        self.send_response(200)
        ctype = "application/pdf" if fn.lower().endswith(".pdf") else "application/octet-stream"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{fn}"')
        self.send_header("Content-Length", str(st.st_size))
        self.end_headers()
        with open(p, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        email = (self.headers.get("Remote-Email") or "").strip()
        try:
            if path in ("/", "/index.html"):
                title = f"CloudFiles: {email}" if email else "CloudFiles"
                email_span = (f'<span class="cb-email">{html.escape(email)}</span>'
                              if email else "")
                g_label, g_cls = _shared_state(email)
                page = PAGE % {
                    "TITLE": title,
                    "FAVICON_B64": FAVICON_B64,
                    "EMAIL_SPAN": email_span,
                    "SECRETS_URL": html.escape(SECRETS_URL, quote=True),
                    "BROWSER_URL": html.escape(BROWSER_URL, quote=True),
                    "GRANTHUB_URL": html.escape(GRANTHUB_URL, quote=True),
                    "SHARED_LABEL": html.escape(g_label),
                    "SHARED_CLS": g_cls,
                }
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/files":
                self._send(200, json.dumps(list_files_for(email)).encode())
            elif path == "/health":
                self._send(200, b'{"ok":true}')
            elif path.startswith("/file/"):
                self._serve_file(path[len("/file/"):], email)
            elif path.startswith("/dl/"):
                self._serve_file(path[len("/dl/"):], email)
            else:
                self._send(404, b'{"error":"not found"}')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print(f"[downloads-api] {path}: {e}", flush=True)
            try:
                self._send(500, b'{"error":"internal"}')
            except Exception:
                pass


def main():
    os.makedirs(DOWNLOADS, exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"downloads-api: serving {DOWNLOADS} on :{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
