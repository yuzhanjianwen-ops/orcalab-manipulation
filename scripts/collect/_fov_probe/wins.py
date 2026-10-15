# -*- coding: utf-8 -*-
import sys, io, ctypes, os, time
from ctypes import wintypes
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from PIL import ImageGrab
u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
rows = []
def cb(h, l):
    pid = ctypes.c_ulong(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    n = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, n, 512)
    if pid.value == 28268 and n.value.strip():
        r = wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r))
        vis = bool(u.IsWindowVisible(h))
        rows.append((h, n.value, r.left, r.top, r.right-r.left, r.bottom-r.top, vis))
    return True
u.EnumWindows(CB(cb), None)
for h, n, x, y, w, ht, vis in rows:
    print("hwnd=%d vis=%s %dx%d at(%d,%d) %r" % (h, vis, w, ht, x, y, n[:70]))
OUT = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\wins"
os.makedirs(OUT, exist_ok=True)
for h, n, x, y, w, ht, vis in rows:
    if vis and w > 300 and ht > 300:
        try:
            img = ImageGrab.grab(bbox=(x, y, x+w, y+ht))
            fp = os.path.join(OUT, "win_%d_%dx%d.png" % (h, w, ht))
            img.save(fp); print("  saved", fp, img.size)
        except Exception as e:
            print("  grab err", h, e)