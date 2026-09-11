"""Synthetic X input-state probe for the disposable :99 display only."""
import ctypes as c


def held_input(*, press=False):
    x = c.CDLL("libX11.so.6")
    t = c.CDLL("libXtst.so.6")
    x.XOpenDisplay.argtypes = [c.c_char_p]
    x.XOpenDisplay.restype = c.c_void_p
    x.XDefaultRootWindow.argtypes = [c.c_void_p]
    x.XDefaultRootWindow.restype = c.c_ulong
    x.XQueryKeymap.argtypes = [c.c_void_p, c.c_char_p]
    x.XQueryPointer.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong),
        c.POINTER(c.c_ulong), c.POINTER(c.c_int), c.POINTER(c.c_int),
        c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_uint)]
    x.XSync.argtypes = [c.c_void_p, c.c_int]
    x.XCloseDisplay.argtypes = [c.c_void_p]
    t.XTestFakeKeyEvent.argtypes = [c.c_void_p, c.c_uint, c.c_int, c.c_ulong]
    t.XTestFakeButtonEvent.argtypes = [c.c_void_p, c.c_uint, c.c_int, c.c_ulong]
    d = x.XOpenDisplay(b":99")
    assert d
    try:
        if press:
            assert t.XTestFakeKeyEvent(d, 50, 1, 0)
            assert t.XTestFakeButtonEvent(d, 1, 1, 0)
            x.XSync(d, 0)
        keys = c.create_string_buffer(32)
        x.XQueryKeymap(d, keys)
        root, child = c.c_ulong(), c.c_ulong()
        coordinates = [c.c_int() for _ in range(4)]
        mask = c.c_uint()
        assert x.XQueryPointer(d, x.XDefaultRootWindow(d), c.byref(root), c.byref(child),
            *(c.byref(v) for v in coordinates), c.byref(mask))
        return bool(keys.raw[50 // 8] & (1 << (50 % 8))), bool(mask.value & (1 << 8))
    finally:
        x.XCloseDisplay(d)
