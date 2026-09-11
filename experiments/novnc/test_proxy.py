"""Run inside the running synthetic container: python3 /app/experiment/test_proxy.py.

Tests use disposable cookies internally and never print them. No external hosts.
"""
import http.client
import socket
import unittest
import ssl
import time

BASE = ("127.0.0.1", 6080)
ORIGIN = "https://127.0.0.1:16080"


def cookie():
    client = http.client.HTTPSConnection(*BASE, timeout=2, context=ssl._create_unverified_context())
    try:
        client.request("POST", "/ui/viewer/session", headers={"Origin": ORIGIN})
        response = client.getresponse()
        assert response.status == 204
        return response.getheader("Set-Cookie").split(";", 1)[0]
    finally:
        client.close()


def connect(value="", origin=ORIGIN, path="/websockify"):
    client = ssl._create_unverified_context().wrap_socket(socket.create_connection(BASE, timeout=2), server_hostname="127.0.0.1")
    request = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:16080\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
               f"Sec-WebSocket-Version: 13\r\nOrigin: {origin}\r\nCookie: {value}\r\n\r\n")
    client.sendall(request.encode())
    return client


def revoke(value):
    client = http.client.HTTPSConnection(*BASE, timeout=2, context=ssl._create_unverified_context())
    try:
        client.request("POST", "/fixture-revoke", headers={"Cookie": value, "Origin": ORIGIN})
        assert client.getresponse().status == 204
    finally:
        client.close()


class ProxyTests(unittest.TestCase):
    def assert_denied(self, client):
        with client:
            received = b""
            while True:
                try:
                    part = client.recv(4096)
                except ConnectionResetError:
                    break
                if not part:
                    break
                received += part
            self.assertNotIn(b"RFB 003", received)
            self.assertNotIn(b"101 Switching", received)

    def test_missing_cookie(self):
        self.assert_denied(connect())

    def test_wrong_origin(self):
        self.assert_denied(connect(cookie(), origin="http://untrusted.example.test"))

    def test_wrong_path(self):
        self.assert_denied(connect(cookie(), path="/other"))

    def test_revoked_cookie(self):
        value = cookie()
        revoke(value)
        self.assert_denied(connect(value))

    def test_connected_idle_stream_is_closed_on_revoke(self):
        value = cookie()
        with connect(value) as client:
            received = b""
            while b"RFB 003" not in received:
                part = client.recv(4096)
                self.assertTrue(part, "stream closed before protocol banner")
                received += part
                self.assertLess(len(received), 65536)
            self.assertIn(b"101 Switching", received)
            revoke(value)
            # A static stream must close without waiting for a new VNC frame.
            while client.recv(4096):
                pass

    def test_z_fence_enable_and_unrenewed_expiry(self):
        # Last test: replaces the startup controller's ticket, intentionally
        # preventing its worker from renewing this new lease.
        from cloudbrowser.browser_slots.lifecycle import BrowserBinding
        from cloudbrowser.viewer.fence_control import ViewerFenceClient
        binding = BrowserBinding("fixture-profile", "fixture-owner", "fixture-browser", "fixture-g1")
        client = ViewerFenceClient(base_url="http://127.0.0.1:6083",
            shared_secret="synthetic-novnc-control-secret-only-32")
        old_cookie = cookie()
        client(binding)
        self.assert_denied(connect(old_cookie))
        with self.assertRaises(AssertionError):
            cookie()
        client.enable(binding)
        fresh_cookie = cookie()
        self.assertNotEqual(old_cookie, fresh_cookie)
        self.assert_denied(connect(old_cookie))
        with connect(fresh_cookie) as stream:
            received = b""
            while b"RFB 003" not in received:
                part = stream.recv(4096)
                self.assertTrue(part)
                received += part
            time.sleep(16)
            # Closed even though no new framebuffer message was requested.
            while stream.recv(4096):
                pass
        with self.assertRaises(AssertionError):
            cookie()
        self.assert_denied(connect(fresh_cookie))


if __name__ == "__main__":
    unittest.main()
