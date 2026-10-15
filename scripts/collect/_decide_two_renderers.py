# -*- coding: utf-8 -*-
"""钉死根因：**引擎离屏渲染** vs **编辑器渲染**，到底谁在拍、拍到了什么。

四个画面（同一时刻）：
  A. AgentCamera_color_1.png            <- 引擎离屏采集相机（数据采集真正走的就是它）
  B. Studio 渲染 @ 引擎报告的 AgentCamera 位姿 [22.496,-3.531,12.582]
  C. Studio 渲染 @ 视口 idx1(camera_head) 位姿 [18.057,-3.377,2.116]
  D. 编辑器屏幕上的 idx1 视口

判读：
  A≈B  -> 引擎离屏相机位姿就是那个自由相机位姿（报告可信），
          那 A 与 D 的差异就只能来自 **两个渲染器/两份场景不一致**
  A≠B  -> 引擎报告的位姿根本不是那台相机的位姿

产出： _fov_probe/twoRenderers/  +  two_renderers_montage.png
"""
import os
import sys
import io
import json
import time
import base64
import shutil
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageDraw, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "twoRenderers")
os.makedirs(OUT, exist_ok=True)
AGENT = os.path.expanduser("~/.orcalab/viewport_image/color/AgentCamera_color_%d.png")

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


log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


def render(pose, index):
    r = m.call("get_view_png_from_transform",
               {"position": list(pose[0]), "rotation": list(pose[1]), "index": index},
               timeout=60)
    if "error" in r:
        return None
    for c in (r.get("result", {}) or {}).get("content", []) or []:
        if c.get("type") == "image":
            return Image.open(io.BytesIO(base64.b64decode(c["data"]))).convert("RGB")
    return None


def cmp(a, b):
    if a is None or b is None:
        return None
    x = np.asarray(a.convert("L").resize((256, 256), Image.LANCZOS), dtype=np.float32)
    y = np.asarray(b.convert("L").resize((256, 256), Image.LANCZOS), dtype=np.float32)
    return float(np.abs(x - y).mean())


m = OrcaMcp()
m.connect()
say("sim:", call_text(m, "get_simulation_state", {})[:80])
hw = find_orca()

# 1) 先把视口切到 idx1 并触发一次离屏落盘
try:
    call_text(m, "set_viewport_camera", {"camera_index": 1})
except Exception as e:
    say("set_viewport_camera err", str(e)[:70])
time.sleep(1.3)
info = call_text(m, "get_viewport_camera_info", {"index": 1})
say("get_viewport_camera_info(1) ->", info[:260])
agent_pose = json.loads(info).get("transform", {})
time.sleep(1.0)

screen = gl_crop(grab(hw))
screen.save(os.path.join(OUT, "D_screen_idx1.png"))

A = None
if os.path.exists(AGENT % 1):
    shutil.copy(AGENT % 1, os.path.join(OUT, "A_agent_cam1.png"))
    A = Image.open(AGENT % 1).convert("RGB")
say("A 引擎离屏 AgentCamera_color_1.png :", None if A is None else A.size)

B = render((agent_pose["position"], agent_pose["rotation"]), 700)
if B is not None:
    B.save(os.path.join(OUT, "B_studio_at_agent_pose.png"))
say("B Studio渲染@AgentCamera位姿 :", None if B is None else B.size)

C = render(([18.057, -3.3775, 2.1156], [-29.142, -0.114, 90.364]), 701)
if C is not None:
    C.save(os.path.join(OUT, "C_studio_at_idx1_pose.png"))
say("C Studio渲染@idx1真实位姿 :", None if C is None else C.size)

say("")
say("A vs B (同一位姿，引擎渲染器 vs Studio渲染器) =", "%.2f" % cmp(A, B) if cmp(A, B) is not None else "n/a")
say("B vs D (Studio渲染 vs 编辑器屏幕, 同一位姿)   =", "%.2f" % cmp(B, screen) if cmp(B, screen) is not None else "n/a")
say("C vs D (Studio@idx1位姿 vs 编辑器屏幕idx1)   =", "%.2f" % cmp(C, screen) if cmp(C, screen) is not None else "n/a")
say("A vs D (引擎离屏 vs 编辑器屏幕)              =", "%.2f" % cmp(A, screen) if cmp(A, screen) is not None else "n/a")

try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass

# ---------------------------------------------------------------- 拼图
TH = 360
GAP = 10
LAB = 26
items = [("A 引擎离屏渲染\n(采集真正走的这条)", A),
         ("B Studio渲染\n@引擎报告的相机位姿", B),
         ("C Studio渲染\n@idx1相机真实位姿", C),
         ("D 编辑器屏幕\n(idx1 视口, 你要的构图)", screen)]
tiles = []
for t, im in items:
    if im is None:
        tiles.append((t, Image.new("RGB", (TH, TH), (40, 40, 40))))
    else:
        w = max(120, int(im.width * TH / im.height))
        tiles.append((t, im.resize((w, TH), Image.LANCZOS)))

W = sum(t[1].width for t in tiles) + GAP * (len(tiles) + 1)
H = 30 + LAB + TH + GAP
M = Image.new("RGB", (W, H), (14, 14, 16))
d = ImageDraw.Draw(M)
d.text((GAP, 8), "同一时刻四个画面：引擎离屏采集 / Studio按引擎位姿渲染 / Studio按idx1位姿渲染 / 编辑器屏幕",
       fill=(255, 220, 0))
x = GAP
for t, im in tiles:
    d.text((x, 30), t, fill=(0, 255, 140))
    M.paste(im, (x, 30 + LAB))
    x += im.width + GAP
o = os.path.join(OUT, "two_renderers_montage.png")
M.save(o)
say("saved", o, M.size)
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE", OUT)
