# -*- coding: utf-8 -*-
"""抓 OrcaStudio 主窗口（标题含 26.8.1），用于确认视口相机切换 UI。"""
import os, sys, io, ctypes
from ctypes import wintypes
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from PIL import ImageGrab

u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
found = []


def cb(h, l):
    n = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, n, 512)
    if n.value.strip() and u.IsWindowVisible(h):
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        r = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        found.append((h, pid.value, n.value, r))
    return True


u.EnumWindows(CB(cb), None)
OUT = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\ui"
os.makedirs(OUT, exist_ok=True)

for h, pid, title, r in found:
    if "26.8.1" in title or "OrcaStudio" in title or "OrcaLab" in title:
        w, ht = r.right - r.left, r.bottom - r.top
        print("WIN pid=%d  %dx%d  %r" % (pid, w, ht, title[:70]))
        try:
            img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
            fp = os.path.join(OUT, "orca_win_%d.png" % h)
            img.save(fp)
            print("   ->", fp, img.size)
        except Exception as e:
            print("   grab err", e)
print("total visible windows:", len(found))
top = [f for f in found if f[3].right - f[3].left > 900 and f[3].bottom - f[3].top > 600]
print("large windows:")
for h, pid, t, r in top:
    print("   pid=%d %dx%d %r" % (pid, r.right - r.left, r.bottom - r.top, t[:70]))
