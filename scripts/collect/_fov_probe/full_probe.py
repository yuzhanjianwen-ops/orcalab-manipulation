# -*- coding: utf-8 -*-
import os, sys, io, json, time, shutil, ctypes
from ctypes import wintypes
sys.path.insert(0, r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\vp3"
os.makedirs(OUT, exist_ok=True)
m = OrcaMcp(); m.connect()

# 0) all actors (camera related)
allA = json.loads(call_text(m, "get_all_actors", {}))
print("=== actors with 'camera' ===")
for k, v in allA.items():
    if "camera" in k.lower():
        print("  ", k, v.get("type"), v.get("transform.position"))
print("=== all top-level actors ===")
for k in allA: 
    if k.count("/") == 1:
        print("  ", k, allA[k].get("type"))

# 1) window grab
u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
hs = []
def cb(h, l):
    pid = ctypes.c_ulong(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value == 28268:
        n = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, n, 512)
        if u.IsWindowVisible(h) and n.value.strip() and "26." in n.value:
            hs.append(h)
    return True
u.EnumWindows(CB(cb), None)
wg = None
if hs:
    r = wintypes.RECT(); u.GetWindowRect(hs[0], ctypes.byref(r))
    wg = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
    wg.save(os.path.join(OUT, "window_now.png"))
    print("window grab", wg.size, "-> window_now.png")

# 2) viewport camera info
info = json.loads(call_text(m, "get_viewport_camera_info"))
print("viewport info transform:", info["transform"])

# 3) render all indices
for i in range(6):
    try:
        r = call_text(m, "get_viewport_png", {"index": i})
        print("png idx", i, "resp:", r[:80])
    except Exception as e:
        print("png idx", i, "ERR", str(e)[:80])
    time.sleep(0.3)
for i in range(6):
    src = os.path.expanduser("~/.orcalab/viewport_color_%d.png") % i
    dst = os.path.join(OUT, "vp_idx%d.png" % i)
    try:
        shutil.copy(src, dst); print("copied idx", i, Image.open(dst).size)
    except Exception as e:
        print("copy idx", i, "ERR", str(e)[:80])