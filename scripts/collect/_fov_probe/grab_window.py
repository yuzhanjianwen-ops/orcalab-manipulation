# -*- coding: utf-8 -*-
import os, sys, io, ctypes
from ctypes import wintypes
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
try:
    from PIL import ImageGrab
except Exception as e:
    print("PIL", e); raise
u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
found = []
def cb(h, l):
    pid = ctypes.c_ulong(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value == 28268:
        n = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, n, 512)
        if u.IsWindowVisible(h) and n.value.strip():
            r = wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r))
            found.append((h, n.value, r))
    return True
u.EnumWindows(CB(cb), None)
OUT = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe"
os.makedirs(OUT, exist_ok=True)
for h, n, r in found:
    w, ht = r.right - r.left, r.bottom - r.top
    print("WIN", repr(n[:50]), "rect", r.left, r.top, w, ht)
    if "Editor" in n or "26.8.1" in n or "RunTime" in n:
        try:
            img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
            fp = os.path.join(OUT, "window_grab_%d.png" % h)
            img.save(fp)
            print("   saved", fp, img.size)
        except Exception as e:
            print("   grab err", e)