#!/usr/bin/env python3
"""title-proxy: reverse proxy in front of the neko viewer (8081 -> neko 8080).

Rewrites the HTML <title> so the browser tab shows "CloudBrowser: <email>"
instead of "n.eko". The per-user email comes from the Remote-Email header
that tinyauth's forwardAuth middleware injects (authResponseHeaders:
remote-user, remote-email, remote-name, remote-groups).

Toolbar URLs come from env (FILES_URL, SECRETS_URL — Coolify service env,
set per stack so both the fleet and the viewer point at their own surfaces).

Also relays WebSocket upgrades (neko signaling, /ws) via a raw TCP pump,
and passes cookies through (neko login session). Only the initial HTML is
rewritten; the neko client JS never sets document.title itself (verified
2026-08-18: app bundle only READS it for history.pushState).

Why: the neko client's <title>n.eko</title> is static in the served
index.html (no NEKO_NAME templating, no client-side override) and neko has
no per-user notion of identity — the email is only known to the auth layer.

Deploy: supervisord program (title-proxy.conf) in the scripts volume;
Coolify UI-managed domain must point at port 8081 instead of 8080.
"""
import base64
import json
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

UPSTREAM = ("127.0.0.1", 8080)
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
TITLE_RE = re.compile(r"<title[^>]*>.*?</title>", re.I | re.S)
# Spec 51 (2026-08-23, Tigo): neko's client persists the login display
# name in localStorage["displayname"] and only falls back to the ?usr=
# URL param when that key is empty. A stale "admin" value (from an early
# manual login) made every kiosk auto-login connect as the generic admin
# user — the UI showed "AD" instead of the real user. This non-defer
# script runs before the deferred app bundle (all neko scripts are
# defer), so the client store init picks up the URL identity. No-op
# without ?usr=; localStorage writes are per-origin (kiosk profile).
_IDENTITY_SCRIPT = (
    "<script>"
    "(function(){"
    "var u=new URL(location.href).searchParams.get(\"usr\");"
    "if(u){try{localStorage.setItem(\"displayname\",u);}catch(e){}}"
    "})();"
    "</script>"
)
HEAD_RE = re.compile(r"<head[^>]*>", re.I)
# PMO City brand mark (from https://pmo.city/ navbar, 2026-08-22). Swaps
# neko's cat favicon for the PMO City logo on the session page (Tigo 2026-08-22).
_PMO_LOGO = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 470">'
             '<path fill-rule="evenodd" fill="#3D6475" '
             'd="M 60,235 A 190,190 0 1,0 440,235 A 190,190 0 1,0 60,235 Z '
             'M 118,235 A 132,132 0 1,1 382,235 A 132,132 0 1,1 118,235 Z"/>'
             '<rect x="22" y="210" width="456" height="50" fill="#3D6475"/>'
             '<circle cx="250" cy="235" r="72" fill="#6DD5B5"/></svg>')
_PMO_LOGO_B64 = base64.b64encode(_PMO_LOGO.encode("utf-8")).decode("ascii")
_FAVICON_LINK = ('<link rel="icon" type="image/svg+xml" '
                 f'href="data:image/svg+xml;base64,{_PMO_LOGO_B64}">')
ICON_RE = re.compile(rb'<link[^>]*rel="(?:icon|apple-touch-icon|mask-icon)"[^>]*>',
                     re.I)

# Surface URLs — Coolify service env (BROWSER_URL/FILES_URL/SECRETS_URL), set
# at Coolify level so they survive redeploys. Defaults are template-safe.
FILES_URL = os.environ.get("FILES_URL", "https://files.example.com/")
SECRETS_URL = os.environ.get("SECRETS_URL", "https://vaultwarden.example.com/")
# Spec 37: GrantHub "Shared" pill. GRANTHUB_STATUS_URL optional JSON
# endpoint {"shared": bool} keyed by Remote-Email; unset/unreachable →
# "Not Shared" (never a false green).
GRANTHUB_URL = os.environ.get("GRANTHUB_URL", "https://cloudbrowser.dev01.pmo.city/connect")
GRANTHUB_STATUS_URL = os.environ.get("GRANTHUB_STATUS_URL", "")


def _internal_status_url() -> str:
    """Resolve GRANTHUB_STATUS_URL for a server-side call. The env value is
    the browser-facing, same-domain path (/connect/status); server-side
    fetches must target the router service over the compose network."""
    if not GRANTHUB_STATUS_URL:
        return ""
    if GRANTHUB_STATUS_URL.startswith(("http://", "https://")):
        return GRANTHUB_STATUS_URL
    return "http://router:8081" + GRANTHUB_STATUS_URL


def _shared_state(email: str) -> tuple:
    """Return (label, color) for the GrantHub Shared pill.

    Spec 59: GREEN ONLY when the grant is USABLE — both the vault key
    and the session-token leg present (the broker can actually read the
    user's vault). A key-only grant renders red until the session leg is
    captured — never a false green."""
    status_url = _internal_status_url()
    if status_url:
        try:
            req = Request(
                status_url,
                headers={"Remote-Email": email, "Accept": "application/json"},
            )
            with urlopen(req, timeout=3) as r:
                if json.loads(r.read().decode("utf-8", "replace")).get("usable"):
                    return ("🔗 Shared", "#22c55e")
        except Exception:
            pass
    return ("🔗 Not Shared", "#ef4444")


def pump(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep supervisord logs quiet
        pass

    # ---- helpers -------------------------------------------------------
    def _user_email(self):
        email = (self.headers.get("Remote-Email") or "").strip()
        if not email:
            # Direct-slot access (bypassing router/tinyauth): the Open
            # Browser href carries usr=<email> — use it as fallback.
            qs = parse_qs(urlparse(self.path).query)
            email = (qs.get("usr") or [""])[0].strip()
        return email

    def _user_title(self):
        email = self._user_email()
        return f"CloudBrowser: {email}" if email else "CloudBrowser"

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else None

    def _forward_headers(self, exclude=()):
        """Build upstream headers: drop hop-by-hop + excluded, fix Host."""
        out = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in HOP_BY_HOP or lk in exclude or lk == "host":
                continue
            out[k] = v
        out["Host"] = f"{UPSTREAM[0]}:{UPSTREAM[1]}"
        out["Accept-Encoding"] = "identity"  # avoid gzip so we can rewrite
        return out

    # ---- websocket relay ----------------------------------------------
    def _relay_ws(self):
        sock = socket.create_connection(UPSTREAM, timeout=5)
        sock.settimeout(None)  # relay fix: never let the 5s connect timeout kill idle pumps (neko heartbeat is 120s)
        try:
            req_line = f"{self.command} {self.path} HTTP/1.1"
            headers = [req_line]
            for k, v in self.headers.items():
                if k.lower() == "host":
                    continue
                headers.append(f"{k}: {v}")
            headers.append(f"Host: {UPSTREAM[0]}:{UPSTREAM[1]}")
            headers.append("\r\n")
            sock.sendall(("\r\n".join(headers)).encode("latin-1"))

            # read upstream response head
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                buf += chunk
            head, _, rest = buf.partition(b"\r\n\r\n")
            status_line, _, _ = head.partition(b"\r\n")
            self.wfile.write(status_line + b"\r\n")
            for line in head.split(b"\r\n")[1:]:
                self.wfile.write(line + b"\r\n")
            self.wfile.write(b"\r\n")
            self.wfile.flush()
            if rest:
                self.wfile.write(rest)
                self.wfile.flush()
            if b"101" not in status_line:
                return
        except OSError:
            try:
                sock.close()
            except OSError:
                pass
            return

        t1 = threading.Thread(target=pump, args=(sock, self.connection), daemon=True)
        t2 = threading.Thread(target=pump, args=(self.connection, sock), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            sock.close()
        except OSError:
            pass

    # ---- http ----------------------------------------------------------
    def _proxy(self):
        if (self.headers.get("Upgrade") or "").lower() == "websocket":
            self._relay_ws()
            return
        body = self._read_body()
        url = f"http://{UPSTREAM[0]}:{UPSTREAM[1]}{self.path}"
        req = Request(url, data=body, method=self.command, headers=self._forward_headers())
        try:
            resp = urlopen(req, timeout=60)
        except HTTPError as e:
            resp = e
        except URLError:
            self.send_error(502, "upstream unreachable")
            return
        data = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        if "text/html" in ctype.lower():
            new_title = self._user_title()
            html = data.decode("utf-8", "replace")
            html = TITLE_RE.sub(f"<title>{new_title}</title>", html)
            # Spec 51: inject the identity script right after <head> so it
            # runs BEFORE the deferred neko app bundle (store init reads
            # localStorage["displayname"]).
            html = HEAD_RE.sub(lambda m: m.group(0) + _IDENTITY_SCRIPT, html)
            data = html.encode("utf-8")
            # neko cat favicon → PMO City logo: first icon link replaced, rest
            # dropped (neko ships icon/16, icon/32, apple-touch, mask-icon)
            _n = [0]
            _fav = _FAVICON_LINK.encode("utf-8")

            def _icon_repl(_m):
                _n[0] += 1
                return _fav if _n[0] == 1 else b""

            data = ICON_RE.sub(_icon_repl, data)
            # Toolbar app shortcuts: open in the PARENT browser (window target)
            # so sessions/autofill live on the user's machine. Vaultwarden
            # (secrets) and Files (cloudfiles = public door to the same
            # per-user download area). Injected post-render; re-applied if Vue
            # re-renders. Spec 37 (LOCKED) order: CloudFiles | Secrets·Shared
            # | email — Secrets+Shared are ONE block (no separator between
            # them); Shared reflects GrantHub state (green/red, never a false
            # green). neko's own chrome (mouse toggle, admin locks,
            # file-transfer toggle, burger) is removed and the brand link
            # (neko GitHub) is neutralized, so the session header matches the
            # queue/landing page top bar.
            email = self._user_email()
            g_label, g_color = _shared_state(email)
            script = (
                "<script>(function(){var E=%s;"
                "function addTool(m,cls,label,href,col,main){"
                "if(m.querySelector('.'+cls))return;"
                "var li=document.createElement('li');li.className=cls;"
                "li.style.cssText='display:inline-flex;align-items:center;margin-right:10px;';"
                "var a=document.createElement('a');a.textContent=label;a.href=href;"
                "a.rel='noopener';"
                "if(main){a.target='_blank';}"
                "if(!main){"
                "/* CloudFiles + Secrets are ALWAYS plain main-browser links "
                "(Tigo 2026-08-23): files must be downloadable on the main "
                "computer — inside the kiosk there is no way to get the file "
                "out. So main=true for both; only the GrantHub Shared pill "
                "opens in the kiosk (capture happens there). */"
                "a.onclick=function(ev){ev.preventDefault();"
                "if(a.dataset.busy)return;"
                "a.dataset.busy='1';var busy=label;"
                "if(busy.length>2){busy=busy.slice(0,2)+' '+busy.slice(2);}"
                "a.textContent=busy+'…';"
                "fetch('/kiosk/open?url='+encodeURIComponent(href),"
                "{method:'POST',headers:{'Accept':'application/json'}})"
                ".then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);"
                "return r.json();})"
                ".then(function(){a.textContent=label;delete a.dataset.busy;})"
                ".catch(function(){a.textContent=label+' ✗';"
                "setTimeout(function(){a.textContent=label;"
                "delete a.dataset.busy;},2000);});}"
                "}"
                "a.style.cssText='font-size:12px;font-weight:500;color:#c9cdd8;"
                "background:rgba(255,255,255,.08);padding:3px 9px;border-radius:4px;"
                "text-decoration:none;white-space:nowrap;display:inline-flex;"
                "cursor:pointer;align-items:center;';"
                "if(col){a.style.color=col;}"
                "a.onmouseover=function(){a.style.background='rgba(255,255,255,.2)';a.style.color=col||'#fff';};"
                "a.onmouseout=function(){a.style.background='rgba(255,255,255,.08)';a.style.color=col||'#c9cdd8';};"
                "li.appendChild(a);m.insertBefore(li,m.firstChild);}"
                "function addSep(m,cls){if(m.querySelector('.'+cls))return;"
                "var li=document.createElement('li');li.className=cls;"
                "li.style.cssText='display:inline-flex;align-items:center;margin:0 6px;';"
                "var sp=document.createElement('span');"
                "sp.style.cssText='display:block;width:1px;height:14px;background:rgba(255,255,255,.15);';"
                "li.appendChild(sp);m.insertBefore(li,m.firstChild);}"
                "function ap(){var m=document.querySelector('ul.menu');"
                "if(!m)return;"
                "var br=document.querySelector('a.neko');"
                "if(br){br.removeAttribute('href');br.removeAttribute('title');br.removeAttribute('target');}"
                "/* brand wordmark: <b>C</b>loudbrowser → <b>C</b>loud<b>B</b>rowser (bold C+B rule) */"
                "var bs=document.querySelector('a.neko span');"
                "if(bs&&bs.innerHTML.indexOf('loudbrowser')>=0){"
                "bs.innerHTML=bs.innerHTML.replace('loudbrowser','loud<b>B</b>rowser');}"
                "function rm(s){var e=m.querySelector(s);if(e)e.remove();}"
                "rm('li:has(i.fa-mouse)');rm('li:has(i.fa-lock)');rm('li:has(i.fa-lock-open)');"
                "rm('li:has(i.fa-bars)');rm('li:has(i.fa-file)');"
                "if(!m.querySelector('.cb-email-li')&&E){"
                "var li=document.createElement('li');li.className='cb-email-li';"
                "li.style.cssText='display:inline-flex;align-items:center;"
                "margin-right:14px;pointer-events:none;user-select:none;';"
                "var s=document.createElement('span');s.className='cb-email';"
                "s.textContent=E;s.style.cssText='font-size:13px;font-weight:500;"
                "color:rgba(255,255,255,.72);letter-spacing:.2px;white-space:nowrap;';"
                "li.appendChild(s);m.insertBefore(li,m.firstChild);}"
                "/* spec 65 (2026-08-25): session countdown + Exit button, "
                "RIGHT of the email (client-page top bar — the extension "
                "cannot reach this bar in the user's own browser). Exit = "
                "two-step confirm → POST /session/release (router, "
                "Remote-Email-keyed) → slot /release teardown → poll "
                "/queue/status until inactive → redirect to /. */"
                "var eml=m.querySelector('.cb-email-li');"
                "if(eml){"
                "if(!m.querySelector('.cb-ttl-li')){"
                "var tli=document.createElement('li');tli.className='cb-ttl-li';"
                "tli.style.cssText='display:inline-flex;align-items:center;margin-left:10px;list-style:none;';"
                "var tsp=document.createElement('span');tsp.className='cb-ttl';tsp.textContent='';"
                "tsp.style.cssText='font-size:12px;font-weight:500;color:#fbbf24;letter-spacing:.2px;white-space:nowrap;';"
                "tli.appendChild(tsp);tli.hidden=true;}"
                "if(!m.querySelector('.cb-exit-li')){"
                "var xli=document.createElement('li');xli.className='cb-exit-li';"
                "xli.style.cssText='display:inline-flex;align-items:center;margin-left:10px;list-style:none;';"
                "var xa=document.createElement('a');xa.href='#';xa.className='cb-exit-btn';"
                "xa.textContent='⏏ Exit session';"
                "xa.style.cssText='font-size:12px;font-weight:500;color:#ff9d9d;background:rgba(255,255,255,.08);padding:3px 9px;border-radius:4px;text-decoration:none;white-space:nowrap;display:inline-flex;cursor:pointer;align-items:center;';"
                "xa.onmouseover=function(){xa.style.background='rgba(255,255,255,.2)';};"
                "xa.onmouseout=function(){xa.style.background='rgba(255,255,255,.08)';};"
                "xa.onclick=function(ev){ev.preventDefault();"
                "if(xa.dataset.armed){delete xa.dataset.armed;xa.style.pointerEvents='none';xa.textContent='⏏ Releasing…';"
                "fetch('/session/release',{method:'POST',headers:{'Accept':'application/json'}})"
                ".then(function(r){return r.json().then(function(j){return {r:r,j:j};});})"
                ".then(function(x){if(x.r.ok){xa.textContent='✓ Released';"
                "var t=0;(function w(){t+=2;if(t>40)return;"
                "fetch('/queue/status',{cache:'no-store'}).then(function(r){return r.json();})"
                ".then(function(j){if(j&&j.status&&j.status!=='active'){location.href='/';}"
                "else{setTimeout(w,2000);}}).catch(function(){setTimeout(w,2000);});})();}"
                "else{xa.textContent='⏏ Exit session';xa.style.pointerEvents='';}}) "
                ".catch(function(){xa.textContent='⏏ Exit session';xa.style.pointerEvents='';});return;}"
                "xa.dataset.armed='1';xa.textContent='Release? ✓';"
                "setTimeout(function(){if(xa.dataset.armed){delete xa.dataset.armed;xa.textContent='⏏ Exit session';}},6000);};"
                "xli.appendChild(xa);eml.insertAdjacentElement('afterend',xli);"
                "xli.insertAdjacentElement('afterend',tli);}}"
                "/* prepend-in-reverse ⇒ DOM order: files, sep, secrets, shared, sep, email */"
                "addSep(m,'cb-sep-li-2');"
                "addTool(m,'cb-tool-shared',%s,%s,%s);"
                "addTool(m,'cb-tool-vw','🔒 Secrets',%s,false,true);"
                "addSep(m,'cb-sep-li-1');"
                "addTool(m,'cb-tool-files','📁 CloudFiles',%s,false,true);}"
                "ap();new MutationObserver(ap).observe(document.body,"
                "{childList:true,subtree:true});"
                "/* Spec 53: live-flip the GrantHub pill — the top bar is "
                "rendered once at load; poll the status endpoint so a grant/"
                "revoke flips it without reloading the viewer. */"
                "var _ghu=%s;if(_ghu){setInterval(function(){"
                "fetch(_ghu,{cache:'no-store'}).then(function(r){return r.json();})"
                ".then(function(j){var sh=!!(j&&j.ok&&j.usable);"
                "var a=document.querySelector('ul.menu .cb-tool-shared a');"
                "if(a){a.textContent=sh?'🔗 Shared':'🔗 Not Shared';"
                "a.style.color=sh?'#22c55e':'#ef4444';}})"
                ".catch(function(){});},2000);}"
                "/* spec 65 countdown: session TTL from the router "
                "('/queue/status' → session_ttl_s, Remote-Email-keyed), "
                "ticked locally every second; hidden when not active. */"
                "var _tEnd=0;"
                "function _fmtCd(s){s=Math.max(0,Math.floor(s));"
                "var m=Math.floor(s/60),ss=s%%60;"
                "return String(m).padStart(2,'0')+':'+String(ss).padStart(2,'0');}"
                "function _updTtl(){var t=document.querySelector('ul.menu .cb-ttl-li');"
                "if(!t){return;}if(_tEnd<=0){t.hidden=true;return;}"
                "var s=(_tEnd-Date.now())/1000;if(s<=0){t.hidden=true;_tEnd=0;return;}"
                "var sp=t.querySelector('.cb-ttl');"
                "if(sp){sp.textContent='⏳ '+_fmtCd(s);}t.hidden=false;}"
                "setInterval(function(){"
                "fetch('/queue/status',{cache:'no-store'}).then(function(r){return r.json();})"
                ".then(function(j){if(j&&j.status==='active'&&j.session_ttl_s>0)"
                "{_tEnd=Date.now()+j.session_ttl_s*1000;}"
                "else{_tEnd=0;}_updTtl();}).catch(function(){});},15000);"
                "setInterval(_updTtl,1000);"
                "})();</script>"
                % (json.dumps(email), json.dumps(g_label), json.dumps(GRANTHUB_URL),
                   json.dumps(g_color), json.dumps(SECRETS_URL), json.dumps(FILES_URL),
                   json.dumps(GRANTHUB_STATUS_URL))
            )
            data = data.replace(b"</body>",
                                (b"<style>a.neko span b{font-weight:900}</style>"
                                 + script.encode("utf-8") + b"</body>"))
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() in HOP_BY_HOP or k.lower() in ("content-length", "server", "date"):
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _proxy


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", 8081), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
