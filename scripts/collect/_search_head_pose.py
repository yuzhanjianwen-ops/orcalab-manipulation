# -*- coding: utf-8 -*-
"""定位 camera_head 真正该待的位置 —— 扫描偏移，找能拍出「桌面+托盘+药品」的那个点。

背景：视口 idx1(camera_head) 画面上是干净的白桌面 + 木格托盘 + 药瓶药盒（用户要的构图），
      但把这些位姿喂给引擎离屏渲染，得到的却是机器人头部外壳内壁（全黑）。
      => 说明「报告出来的世界位姿」并不是能复现视口画面的位姿，两者差一个偏移。

做法：以报告位姿 p0 为中心，沿 x/y/z 各 ±0.3 / ±0.6 m 共 12 个偏移 + 原位，
      各渲染一张，与编辑器屏幕(idx1)画面做相关性比对，输出最好的一档。

产出： _fov_probe/headPoseSearch/ + head_pose_search_montage.png
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

OUT = os.path.join(HERE, "_fov_probe", "headPoseSearch")
os.makedirs(OUT, exist_ok=True)

P0 = [18.057, -3.3775, 2.1156]
ROT = [-29.142, -0.114, 90.364]

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


def center_sq(im, n=96):
    a = im.convert("L")
    s = min(a.size)
    a = a.crop(((a.width - s) // 2, (a.height - s) // 2,
                (a.width + s) // 2, (a.height + s) // 2)).resize((n, n), Image.LANCZOS)
    return np.asarray(a, dtype=np.float32)


log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


def render(pos, index):
    r = m.call("get_view_png_from_transform",
               {"position": list(pos), "rotation": list(ROT), "index": index}, timeout=60)
    if "error" in r:
        return None
    for c in (r.get("result", {}) or {}).get("content", []) or []:
        if c.get("type") == "image":
            return Image.open(io.BytesIO(base64.b64decode(c["data"]))).convert("RGB")
    return None


m = OrcaMcp()
m.connect()
say("sim:", call_text(m, "get_simulation_state", {})[:70])
hw = find_orca()

# 参考：编辑器屏幕上的 idx1 视口
try:
    call_text(m, "set_viewport_camera", {"camera_index": 1})
except Exception:
    pass
time.sleep(1.3)
ref = gl_crop(grab(hw))
ref.save(os.path.join(OUT, "ref_screen_idx1.png"))
say("参考画面 编辑器屏幕 idx1:", ref.size)
refv = center_sq(ref)

t0 = time.time()
cases = [((0, 0, 0), "原位")]
for d in (0.3, 0.6):
    for ax, nm in ((0, "x"), (1, "y"), (2, "z")):
        for s in (+1, -1):
            o = [0.0, 0.0, 0.0]
            o[ax] = s * d
            cases.append((tuple(o), "%+0.1f%s" % (s * d, nm)))

rows = []
for i, (off, nm) in enumerate(cases):
    pos = [P0[k] + off[k] for k in range(3)]
    img = render(pos, 720 + i)
    if img is None:
        say("  %-8s 渲染失败" % nm)
        continue
    img.save(os.path.join(OUT, "off_%s.png" % nm.replace("+", "p").replace("-", "m").replace(".", "")))
    v = center_sq(img)
    r = float(np.corrcoef(refv.ravel(), v.ravel())[0, 1])
    bright = float((v > 225).mean() * 100)
    rows.append({"off": off, "name": nm, "corr": r, "bright%": bright,
                 "pos": pos, "img": img})
    say("  %-8s pos=%s  与屏幕相关性=%.3f  纯白占比=%.1f%%" % (
        nm, [round(x, 3) for x in pos], r, bright))

say("渲染耗时 平均 %.2f s/张" % ((time.time() - t0) / max(1, len(cases))))

# 还原视口
try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass

with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as f:
    json.dump([{k: v for k, v in r.items() if k != "img"} for r in rows],
              f, ensure_ascii=False, indent=2)

rows.sort(key=lambda r: -r["corr"])
say("")
say("按相关性排序 Top5:")
for r in rows[:5]:
    say("   %-8s corr=%.3f bright=%.1f%%" % (r["name"], r["corr"], r["bright%"]))

# ---------------------------------------------------------------- 拼图
TH = 250
GAP = 6
show = [{"name": "编辑器屏幕(参考)", "img": ref, "corr": 1.0, "bright%": 0.0}] + rows
cols = 5
rowsn = (len(show) + cols - 1) // cols
LAB = 30
M = Image.new("RGB", (cols * (TH + GAP) + GAP, rowsn * (TH + LAB + GAP) + GAP + 22), (14, 14, 16))
d = ImageDraw.Draw(M)
d.text((GAP, 6), "camera_head 位姿偏移扫描：找哪一档能拍出「桌子+托盘+药品」（corr=与编辑器屏幕的相似度）",
       fill=(255, 220, 0))
for i, r in enumerate(show):
    cx = GAP + (i % cols) * (TH + GAP)
    cy = 22 + (i // cols) * (TH + LAB + GAP)
    d.text((cx, cy), r["name"], fill=(0, 255, 140))
    d.text((cx, cy + 14), "corr=%.2f  white=%.0f%%" % (r["corr"], r["bright%"]), fill=(255, 180, 0))
    M.paste(r["img"].resize((TH, TH), Image.LANCZOS), (cx, cy + LAB))
o = os.path.join(OUT, "head_pose_search_montage.png")
M.save(o)
say("saved", o, M.size)
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE", OUT)
