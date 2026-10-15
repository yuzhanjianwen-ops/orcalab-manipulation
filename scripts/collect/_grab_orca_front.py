# -*- coding: utf-8 -*-
"""把 OrcaStudio 主窗口切到前台并抓图（供确认视口相机切换 UI）。"""
import os, sys, io, time, ctypes
from ctypes import wintypes
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from PIL import ImageGrab

u = ctypes.windll.user32
TARGET = 29752  # 刚才看到的 OrcaStudio pid
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
hits = []


def cb(h, l):
    n = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, n, 512)
    if u.IsWindowVisible(h) and "26.8.1" in n.value:
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        hits.append((h, pid.value, n.value))
    return True


u.EnumWindows(CB(cb), None)
print("orca windows:", hits)
OUT = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\ui"
os.makedirs(OUT, exist_ok=True)

for h, pid, title in hits:
    try:
        u.ShowWindow(h, 9)           # SW_RESTORE
        u.SetForegroundWindow(h)
        time.sleep(1.2)
        r = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
        fp = os.path.join(OUT, "orca_front_%d.png" % pid)
        img.save(fp)
        print("saved", fp, img.size)
        # 裁剪视口顶部工具栏（右侧 3D 区域上方）
        W, H = img.size
        top = img.crop((int(W * 0.30), 0, W, int(H * 0.10)))
        top.save(os.path.join(OUT, "orca_vp_toolbar_%d.png" % pid))
        print("   toolbar crop", top.size)
    except Exception as e:
        print("err", e)
