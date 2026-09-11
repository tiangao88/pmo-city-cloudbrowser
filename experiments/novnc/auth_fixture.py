"""LOCAL QUALIFICATION ONLY: synthetic cookie is not authentication."""
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        user = cookies.get("fixture_user")
        if self.path != "/check" or user is None or user.value not in ("alice", "bob"):
            self.send_response(401)
        else:
            self.send_response(200)
            self.send_header("Remote-Sub", user.value)
            self.send_header("Remote-Groups", "PMOC_Users")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 8089), Handler).serve_forever()
