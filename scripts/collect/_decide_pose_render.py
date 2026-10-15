# -*- coding: utf-8 -*-
"""决定性实验：引擎离屏渲染为什么拍不到「桌子 / 夹爪」。

思路（把「相机位姿不对」和「引擎场景缺物体」两种情况分开）
=========================================================
对 idx = 0/1/2/3（自由相机 / camera_head / camera_left / camera_right）：
  1) MCP set_viewport_camera(idx)            —— 切编辑器视口相机
  2) MCP get_viewport_transform()            —— 读出这台相机的**真实世界位姿**
  3) 抓 OrcaStudio 窗口并裁出 3D 视口          —— 用户眼睛看到的（作为标尺）
  4) MCP get_view_png_from_transform(该位姿)  —— 让**引擎**用**同一个位姿**渲一张

判读
====
  若 (4) ≈ (3)  -> 引擎场景没问题，是**引擎侧相机位姿**不对（改正位姿即可）
  若 (4) 仍是空棋盘 -> 引擎渲染场景里根本没有桌子（编辑器场景 ≠ 引擎场景）

产出： _fov_probe/poseRender/  +  pose_render_montage.png
"""
import os
import sys
import io
import json
import time
import base64
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageDraw, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "poseRender")
os.makedirs(OUT, exist_ok=True)

IDX = (0, 1, 2, 3)
NAMES = {0: "free/idx0", 1: "camera_head", 2: "camera_left", 3: "camera_right"}

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
    """用指定位姿让引擎渲一张，返回 PIL 图。"""
    r = m.call("get_view_png_from_transform",
               {"position": list(pose["position"]),
                "rotation": list(pose["rotation"]),
                "index": index}, timeout=60)
    if "error" in r:
        return None, json.dumps(r["error"], ensure_ascii=False)[:120]
    for c in (r.get("result", {}) or {}).get("content", []) or []:
        if c.get("type") == "image":
            data = base64.b64decode(c["data"])
            return Image.open(io.BytesIO(data)).convert("RGB"), "%d B" % len(data)
    return None, "non-image: " + json.dumps(r, ensure_ascii=False)[:120]


m = OrcaMcp()
m.connect()
say("sim:", call_text(m, "get_simulation_state", {})[:80])
hw = find_orca()
say("hwnd:", hw)

rows = []
for idx in IDX:
    try:
        call_text(m, "set_viewport_camera", {"camera_index": idx})
    except Exception as e:
        say("idx%d set_viewport_camera err %s" % (idx, str(e)[:70]))
    time.sleep(1.3)

    pose = {}
    try:
        t = json.loads(call_text(m, "get_viewport_transform", {}))
        pose = t.get("transform", t)
    except Exception as e:
        say("idx%d get_viewport_transform err %s" % (idx, str(e)[:70]))
    say("idx%d %-13s pos=%s rot=%s scale=%s" % (
        idx, NAMES[idx],
        [round(v, 3) for v in (pose.get("position") or [])],
        [round(v, 2) for v in (pose.get("rotation") or [])],
        pose.get("scale")))

    try:
        scr = gl_crop(grab(hw))
        scr.save(os.path.join(OUT, "screen_idx%d.png" % idx))
    except Exception as e:
        scr = None
        say("  grab err", str(e)[:80])

    img, info = (None, "no pose")
    if pose.get("position") and pose.get("rotation"):
        img, info = render(pose, 700 + idx)
        if img is not None:
            img.save(os.path.join(OUT, "engine_idx%d.png" % idx))
    say("  engine render: %s" % info)

    # 差异度量：把两张缩到同尺寸比
    d = None
    if img is not None and scr is not None:
        a = np.asarray(scr.convert("L").resize((240, 240), Image.LANCZOS), dtype=np.float32)
        b = np.asarray(img.convert("L").resize((240, 240), Image.LANCZOS), dtype=np.float32)
        d = float(np.abs(a - b).mean())
        say("  屏幕 vs 引擎同姿态渲染 差异 = %.2f" % d)
    rows.append({"idx": idx, "name": NAMES[idx], "pose": pose,
                 "diff": d, "engine_info": info, "screen": scr, "engine": img})

try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass

with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as f:
    json.dump([{k: v for k, v in r.items() if k not in ("screen", "engine")} for r in rows],
              f, ensure_ascii=False, indent=2)

# ------------------------------------------------------------------ 拼图
TH = 330
GAP = 8
LAB = 44
tiles = []
for r in rows:
    if r["screen"] is None:
        continue
    a = r["screen"].resize((int(r["screen"].width * TH / r["screen"].height), TH), Image.LANCZOS)
    if r["engine"] is not None:
        b = r["engine"].resize((int(r["engine"].width * TH / r["engine"].height), TH), Image.LANCZOS)
    else:
        b = Image.new("RGB", a.size, (40, 40, 40))
    tiles.append((r, a, b))

W = sum(t[1].width + t[2].width + GAP * 3 for t in tiles) + GAP
H = 26 + LAB + TH + GAP * 2
M = Image.new("RGB", (W, H), (14, 14, 16))
d = ImageDraw.Draw(M)
d.text((GAP, 7), "左: 编辑器屏幕(用户眼睛看到的)   右: 引擎用同一世界位姿离屏渲染   判定引擎场景/位姿是否一致",
       fill=(255, 220, 0))
x = GAP
for r, a, b in tiles:
    d.text((x, 26), "idx%d %s" % (r["idx"], r["name"]), fill=(0, 255, 140))
    d.text((x, 26 + LAB - 16), "diff=%.1f" % (r["diff"] if r["diff"] is not None else -1),
           fill=(255, 120, 120))
    M.paste(a, (x, 26 + LAB))
    d.text((x + a.width + GAP, 26), "引擎渲染", fill=(255, 180, 0))
    M.paste(b, (x + a.width + GAP * 2, 26 + LAB))
    x += a.width + b.width + GAP * 3

o = os.path.join(OUT, "pose_render_montage.png")
M.save(o)
say("saved", o, M.size)
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE", OUT)
