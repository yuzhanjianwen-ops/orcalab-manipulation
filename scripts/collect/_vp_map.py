# -*- coding: utf-8 -*-
"""把软件视口逐个切到 index 0..5，每个 index 同时抓：
   editor_idxN.png   编辑器窗口（自动裁出 3D 视口区）
   gl_idxN.png       上面裁出来的 3D 区
   agent_idxN.png    离屏 AgentCamera
再和 三路机载推流 做 NCC 比对，判断"编辑器视口 == 哪台相机"。
产出： _fov_probe/vpmap/
"""
import os, sys, io, time, json, ctypes, shutil
from ctypes import wintypes
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "vpmap")
os.makedirs(OUT, exist_ok=True)

u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))


def find_orca():
    hw = []

    def cb(h, l):
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if not u.IsWindowVisible(h):
            return True
        n = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(h, n, 512)
        if n.value.strip().startswith("26.8.1"):
            hw.append(h)
        return True

    u.EnumWindows(CB(cb), None)
    return hw[0] if hw else None


def grab(h):
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.7)
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))


def gl_crop(im):
    W, H = im.size
    a = np.asarray(im, dtype=np.float32)
    panel = np.median(a[300:min(900, H), 10:60, :].reshape(-1, 3), axis=0)
    diff = np.abs(a - panel).mean(axis=2)
    is3d = diff > 18
    col_frac = is3d.mean(axis=0)
    x0 = W
    for x in range(W // 2, 0, -1):
        if col_frac[x] < 0.35 and col_frac[max(0, x - 30):x].mean() < 0.35:
            x0 = x + 1
            break
    row_frac = is3d[:, x0:].mean(axis=1)
    y0 = H
    for y in range(H // 2, 0, -1):
        if row_frac[y] < 0.35 and row_frac[max(0, y - 25):y].mean() < 0.35:
            y0 = y + 1
            break
    return im.crop((x0, y0, W, H)), (x0, y0, W - x0, H - y0)


ap = r"C:\Users\86322\.orcalab\viewport_image\color\AgentCamera_color_0.png"
h = find_orca()
print("orca hwnd:", h)

m = OrcaMcp()
m.connect()
print("state:", call_text(m, "get_simulation_state", {}))

poses = {}
for idx in range(6):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": idx})
    except Exception as e:
        print("idx", idx, "set err", str(e)[:80])
        continue
    time.sleep(1.0)
    try:
        t = json.loads(call_text(m, "get_viewport_transform", {}))
        tr = t.get("transform", t)
        poses[idx] = tr
    except Exception:
        poses[idx] = {}
    if h:
        try:
            im = grab(h)
            im.save(os.path.join(OUT, "editor_idx%d.png" % idx))
            cr, bbox = gl_crop(im)
            cr.save(os.path.join(OUT, "gl_idx%d.png" % idx))
            print("idx%d  window %dx%d  gl %dx%d  pos=%s scale=%s" % (
                idx, im.size[0], im.size[1], cr.size[0], cr.size[1],
                [round(x, 3) for x in poses[idx].get("position", [])], poses[idx].get("scale")))
        except Exception as e:
            print("idx", idx, "grab err", e)
    if os.path.exists(ap):
        try:
            shutil.copy(ap, os.path.join(OUT, "agent_idx%d.png" % idx))
        except Exception as e:
            print("idx", idx, "agent copy err", e)

with open(os.path.join(OUT, "poses.json"), "w", encoding="utf-8") as f:
    json.dump({str(k): v for k, v in poses.items()}, f, ensure_ascii=False, indent=2)
print("DONE")
