"""Own the X/VNC lifetime alongside exactly one existing BrowserProcess.

Candidate runtime only. No shared host display, no second browser launcher.
"""
import ctypes
import socket
import subprocess
import time


def terminate(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def release_inputs():
    """Release keys/buttons on the owned :99 display before agent resume."""
    x11 = ctypes.CDLL("libX11.so.6")
    xtst = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(b":99")
    if not display:
        raise RuntimeError("owned display unavailable")
    try:
        keys = ctypes.create_string_buffer(32)
        x11.XQueryKeymap(display, keys)
        for code in range(8, 256):
            if keys.raw[code // 8] & (1 << (code % 8)):
                if not xtst.XTestFakeKeyEvent(display, code, 0, 0):
                    raise RuntimeError("key release failed")
        for button in range(1, 6):
            if not xtst.XTestFakeButtonEvent(display, button, 0, 0):
                raise RuntimeError("button release failed")
        x11.XSync(display, 0)
    finally:
        x11.XCloseDisplay(display)


class DesktopProcess:
    def __init__(self, process, interaction):
        self._browser = process
        self._interaction = interaction
        self._display = self._vnc = None
        self.fence = lambda: None

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def readiness(self):
        return (self._display is not None and self._display.poll() is None
                and self._vnc is not None and self._vnc.poll() is None
                and self._browser.readiness())

    def recover_if_crashed(self):
        return False  # Supervisor must fence and rebuild the complete display.

    def start(self, **kwargs):
        with self._interaction.lock:
            if self.readiness():
                return True
            self.stop()
            self._interaction.change("initializing")
            self._display = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    if self._display.poll() is not None:
                        raise RuntimeError("display startup failed")
                    if subprocess.run(["xdpyinfo", "-display", ":99"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=1).returncode == 0:
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("display startup timed out")
                self._browser.start(**kwargs)
                self.set_input(False)
                return True
            except BaseException:
                self.stop()
                raise

    def set_input(self, enabled):
        with self._interaction.lock:
            terminate(self._vnc)
            self._vnc = None
            if self._display is None or self._display.poll() is not None:
                if enabled:
                    raise RuntimeError("display unavailable")
                return
            release_inputs()
            if self._browser.state != "ready":
                return
            command = ["x11vnc", "-display", ":99", "-localhost", "-rfbport", "5900",
                "-forever", "-shared", "-nopw", "-nosel", "-noremote", "-noxdamage", "-clear_keys", "-input", "KMB"]
            if not enabled:
                command.append("-viewonly")
            self._vnc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(30):
                if self._vnc.poll() is not None:
                    raise RuntimeError("VNC startup failed")
                try:
                    with socket.create_connection(("127.0.0.1", 5900), timeout=0.1):
                        return
                except OSError:
                    time.sleep(0.1)
            raise RuntimeError("VNC startup timed out")

    def stop(self):
        with self._interaction.lock:
            self.fence()
            self._interaction.change("paused")
            self._browser.stop()
            terminate(self._vnc)
            self._vnc = None
            terminate(self._display)
            self._display = None
