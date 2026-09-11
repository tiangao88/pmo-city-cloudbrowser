"""Bounded binary WebSocket stream adapter for synthetic RFB pixel checks."""
import os
import struct

from test_proxy import connect


class RfbWebSocket:
    def __init__(self, cookie, *, connector=connect):
        self.socket = connector(cookie)
        self.socket.settimeout(10)
        self.wire = bytearray()
        self.data = bytearray()
        while b"\r\n\r\n" not in self.wire:
            part = self.socket.recv(4096)
            assert part
            self.wire.extend(part)
            assert len(self.wire) <= 65536
        headers, tail = bytes(self.wire).split(b"\r\n\r\n", 1)
        assert b"101 Switching" in headers
        self.wire = bytearray(tail)

    def exact(self, size):
        while len(self.wire) < size:
            part = self.socket.recv(min(65536, size - len(self.wire)))
            if not part:
                raise EOFError("WebSocket closed")
            self.wire.extend(part)
        value = bytes(self.wire[:size])
        del self.wire[:size]
        return value

    def sendall(self, data, opcode=2):
        assert len(data) < 65536
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        header += bytes([0x80 | len(data)]) if len(data) < 126 else b"\xfe" + struct.pack("!H", len(data))
        self.socket.sendall(header + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data)))

    def recv(self, size):
        while not self.data:
            try:
                first, second = self.exact(2)
                assert not second & 0x80, "unexpected masked server frame"
                length = second & 127
                if length == 126:
                    length = struct.unpack("!H", self.exact(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self.exact(8))[0]
                assert length <= 4 * 1024 * 1024
                payload = self.exact(length)
            except EOFError:
                return b""
            opcode = first & 15
            if opcode == 8:
                return b""
            if opcode == 9:
                self.sendall(payload, opcode=10)
            elif opcode in (0, 2):
                self.data.extend(payload)
            else:
                raise AssertionError("unexpected WebSocket opcode")
        result = bytes(self.data[:size])
        del self.data[:size]
        return result

    def close(self):
        self.socket.close()
