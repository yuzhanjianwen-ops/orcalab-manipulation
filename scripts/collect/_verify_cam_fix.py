# -*- coding: utf-8 -*-
"""相机修好后的一键验收：编辑器视口画面 vs 引擎离屏渲染画面。

用法
----
    # 1) 直接在编辑器里改完相机，跑验收（不加偏移）
    python _verify_cam_fix.py

    # 2) 先试偏移（不改资产，只在渲染时补偿），看看挪多少才对齐
    python _verify_cam_fix.py --offset 0,-0.3,0
    python _verify_cam_fix.py --offset 0,0,0.3

做什么
------
对 idx = 1/2/3（camera_head / camera_left / camera_right）各做一遍：
  * 50151 切视口相机到该 idx（MCP set_viewport_camera）
  * 抓 OrcaStudio 窗口并裁出 3D 视口          -> 用户眼睛看到的（目标）
  * 读该相机的世界位姿（MCP get_viewport_transform）
  * 引擎用「该位姿 + 偏移」离屏渲染一张        -> 采集实际能拿到的
  * 两者算相似度 -> 打印 PASS / FAIL
输出三联拼图 _fov_probe/verify/verify_montage.png

判读
----
diff 小（< 40）说明两边画面一致 -> 采集链路已经能拿到视口画面
diff 大（~150）说明相机仍被遮挡/位姿不符 -> 继续在 Studio 里挪相机
"""
import os
import sys
import io
import json
import time
import base64
import ctypes
import argparse
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageDraw, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "verify")
os.makedirs(OUT, exist_ok=True)
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


def grab(h, tries=10):
    """抓 OrcaStudio 窗口。

    注意：ImageGrab 抓的是**屏幕区域**，只要别的窗口盖在上面就会抓错。
    所以必须先确认 OrcaStudio 真的成了前台窗口，否则宁可返回 None 报错，
    也不要静默产出一张别的窗口的图（会污染结论）。
    """
    for _ in range(tries):
        try:
            u.ShowWindow(h, 9)          # SW_RESTORE
            u.BringWindowToTop(h)
            u.SetForegroundWindow(h)
        except Exception:
            pass
        time.sleep(0.7)
        if u.GetForegroundWindow() == h:
            time.sleep(0.5)
            r = wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
    return None


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


def score(a, b):
    x = np.asarray(a.convert("L").resize((256, 256), Image.LANCZOS), dtype=np.float32)
    y = np.asarray(b.convert("L").resize((256, 256), Image.LANCZOS), dtype=np.float32)
    return float(np.abs(x - y).mean())


ap = argparse.ArgumentParser()
ap.add_argument("--offset", default="0,0,0", help="渲染时给相机位姿加的偏移, 形如 0,-0.3,0")
ap.add_argument("--idx", default="1,2,3", help="要验收哪几台, 形如 1,2,3")
args = ap.parse_args()
OFF = [float(v) for v in args.offset.split(",")]
IDX = [int(v) for v in args.idx.split(",")]

m = OrcaMcp()
m.connect()
print("sim:", call_text(m, "get_simulation_state", {})[:70])
print("渲染偏移 Δ =", OFF)
hw = find_orca()
print("hwnd:", hw)

rows = []
for i, idx in enumerate(IDX):
    call_text(m, "set_viewport_camera", {"camera_index": idx})
    time.sleep(1.3)
    t = json.loads(call_text(m, "get_viewport_transform", {}))
    tr = t.get("transform", t)
    pos = [float(v) + OFF[k] for k, v in enumerate(tr.get("position", []))]
    rot = [float(v) for v in tr.get("rotation", [])]
    shot = grab(hw)
    if shot is None:
        print("  [warn] 抓不到 OrcaStudio 窗口（没成为前台窗口），idx%d 的屏幕参考缺失" % idx)
        scr = None
    else:
        scr = gl_crop(shot)
        scr.save(os.path.join(OUT, "screen_idx%d.png" % idx))

    r = m.call("get_view_png_from_transform",
               {"position": pos, "rotation": rot, "index": 800 + i}, timeout=90)
    eng = None
    for c in (r.get("result", {}) or {}).get("content", []) or []:
        if c.get("type") == "image":
            eng = Image.open(io.BytesIO(base64.b64decode(c["data"]))).convert("RGB")
    if eng is not None:
        eng.save(os.path.join(OUT, "engine_idx%d.png" % idx))

    d = score(scr, eng) if (eng is not None and scr is not None) else None
    verdict = "N/A" if d is None else ("PASS 一致" if d < 40 else "FAIL 仍不一致")
    print("idx%d %-13s pos=%s  diff=%s  -> %s" % (
        idx, NAMES.get(idx, "?"), [round(v, 3) for v in pos],
        "n/a" if d is None else "%.1f" % d, verdict))
    rows.append((idx, NAMES.get(idx, "?"), scr, eng, d))

call_text(m, "set_viewport_camera", {"camera_index": 0})

TH, GAP, LAB = 380, 10, 30
W = len(rows) * (TH * 2 + GAP * 3) + GAP
H = 26 + LAB + TH + GAP
M = Image.new("RGB", (W, H), (14, 14, 16))
dr = ImageDraw.Draw(M)
dr.text((GAP, 6), "左: 编辑器视口(目标)   右: 引擎离屏渲染(采集实际拿到)   Δ=%s" % OFF, fill=(255, 220, 0))
x = GAP
for idx, nm, scr, eng, d in rows:
    dr.text((x, 26), "idx%d %s  diff=%s" % (idx, nm, "n/a" if d is None else "%.1f" % d),
            fill=(0, 255, 140))
    if scr is not None:
        M.paste(scr.resize((TH, TH), Image.LANCZOS), (x, 24 + LAB))
    dr.text((x + TH + GAP, 26), "引擎离屏", fill=(255, 180, 0))
    if eng is not None:
        M.paste(eng.resize((TH, TH), Image.LANCZOS), (x + TH + GAP, 24 + LAB))
    x += TH * 2 + GAP * 3
o = os.path.join(OUT, "verify_montage.png")
M.save(o)
print("saved", o, M.size)
