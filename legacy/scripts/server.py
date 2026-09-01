#!/usr/bin/env python3
"""W1 spike only — serves the fake login page with credentials from env.

The W1 broker spike needs a target page with a login form whose credentials
live in a Vaultwarden item. Production uses real sites; this fixture is
removed in W2. Credentials come from FAKE_LOGIN_USER / FAKE_LOGIN_PASS
(env), matching the Vaultwarden test item the broker fetches.
"""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

USER = os.environ.get("FAKE_LOGIN_USER", "spike-user")
PASS = os.environ.get("FAKE_LOGIN_PASS", "")

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Fake Login — W1 broker spike</title>
  <style>
    body { font-family: system-ui, sans-serif; display: grid; place-items: center; height: 100vh; margin: 0; background: #f4f4f5; }
    form { background: #fff; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,.08); width: 320px; }
    h1 { font-size: 1.1rem; margin-top: 0; }
    label { display: block; margin: .8rem 0 .3rem; font-size: .85rem; color: #333; }
    input { width: 100%; padding: .5rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
    button { margin-top: 1.2rem; width: 100%; padding: .6rem; background: #2563eb; color: #fff; border: 0; border-radius: 4px; font-size: .95rem; cursor: pointer; }
    .ok { margin-top: 1rem; padding: .6rem; background: #dcfce7; color: #166534; border-radius: 4px; display: none; }
    .fail { margin-top: 1rem; padding: .6rem; background: #fee2e2; color: #991b1b; border-radius: 4px; display: none; }
  </style>
</head>
<body>
  <form id="login">
    <h1>W1 Broker Spike — Fake Login</h1>
    <label for="username">Username</label>
    <input id="username" name="username" autocomplete="off">
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="off">
    <button type="submit">Sign in</button>
    <div id="ok" class="ok">✅ Login accepted for <span id="ok-user"></span></div>
    <div id="fail" class="fail">❌ Invalid credentials</div>
  </form>
  <script>
    const TEST_USER = __USER__;
    const TEST_PASS = __PASS__;
    document.getElementById("login").addEventListener("submit", (e) => {
      e.preventDefault();
      const u = document.getElementById("username").value;
      const p = document.getElementById("password").value;
      if (u === TEST_USER && p === TEST_PASS) {
        document.getElementById("ok-user").textContent = u;
        document.getElementById("ok").style.display = "block";
        document.getElementById("fail").style.display = "none";
      } else {
        document.getElementById("fail").style.display = "block";
        document.getElementById("ok").style.display = "none";
      }
    });
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = HTML.replace("__USER__", f'"{USER}"').replace("__PASS__", f'"{PASS}"')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode())))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):  # silence access logs (no creds anyway)
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
