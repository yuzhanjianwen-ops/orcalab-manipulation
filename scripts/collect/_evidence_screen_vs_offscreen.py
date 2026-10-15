# -*- coding: utf-8 -*-
"""证据图：同一时刻、同一台相机，编辑器屏幕上看到的 vs 引擎离屏渲染出来的。

对 idx = 1/2/3（camera_head / camera_left / camera_right）：
  * 50151 SetActiveCamera(idx)
  * MCP  get_viewport_camera_info(idx)  -> 触发离屏渲染落盘 AgentCamera_color_<idx>.png
  * 抓 OrcaStudio 窗口，裁出右侧 3D 视口   （= 用户眼睛看到的）
产出： _fov_probe/evidence/  +  evidence_montage.png
"""
import os
import sys
import io
import json
import time
import ctypes
import shutil
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageDraw, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "evidence")
os.makedirs(OUT, exist_ok=True)
AGENT = os.path.expanduser("~/.orcalab/viewport_image/color/AgentCamera_color_%d.png")
NAMES = {1: "camera_head", 2: "camera_left", 3: "camera_right"}

u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))


def find_orca():
    hw = []

    def cb(h, l):
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
    time.sleep(0.8)
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
    return im.crop((x0, y0, W, H))


m = OrcaMcp()
m.connect()
print("sim:", call_text(m, "get_simulation_state", {})[:70])
hw = find_orca()
print("hwnd:", hw)

tiles = []
for idx in (1, 2, 3):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": idx})
    except Exception as e:
        print("idx", idx, "set err", str(e)[:80])
    time.sleep(1.2)
    try:
        call_text(m, "get_viewport_camera_info", {"index": idx})
    except Exception:
        pass
    time.sleep(1.0)
    scr = gl_crop(grab(hw))
    scr.save(os.path.join(OUT, "screen_idx%d.png" % idx))
    ap = AGENT % idx
    off = None
    if os.path.exists(ap):
        shutil.copy(ap, os.path.join(OUT, "offscreen_idx%d.png" % idx))
        off = Image.open(ap).convert("RGB")
    print("idx%d %s: screen=%s  offscreen=%s" % (
        idx, NAMES[idx], "%dx%d" % scr.size,
        None if off is None else "%dx%d" % off.size))
    tiles.append((idx, NAMES[idx], scr, off))

try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass

TH = 300
GAP = 8
LAB = 34
pairs = []
for idx, nm, scr, off in tiles:
    a = scr.resize((int(scr.width * TH / scr.height), TH), Image.LANCZOS)
    if off is not None:
        b = off.resize((int(off.width * TH / off.height), TH), Image.LANCZOS)
    else:
        b = Image.new("RGB", a.size, (40, 40, 40))
    pairs.append((idx, nm, a, b))

W = sum(p[2].width + p[3].width + GAP for p in pairs) + GAP * (len(pairs) + 1)
H = 30 + LAB + TH + GAP
M = Image.new("RGB", (W, H), (14, 14, 16))
d = ImageDraw.Draw(M)
d.text((GAP, 6), "同一时刻同一台相机 —— 左格: 编辑器屏幕上的 3D 视口 / 右格: 引擎离屏渲染(采集走的就是这条)",
       fill=(255, 220, 0))
x = GAP
for idx, nm, a, b in pairs:
    d.text((x, 24), "idx%d %s" % (idx, nm), fill=(0, 255, 140))
    M.paste(a, (x, 30 + LAB - 18))
    d.text((x + a.width + 4, 24), "离屏", fill=(255, 180, 0))
    M.paste(b, (x + a.width + GAP, 30 + LAB - 18))
    x += a.width + b.width + GAP * 3
o = os.path.join(OUT, "evidence_montage.png")
M.save(o)
print("saved", o, M.size)
