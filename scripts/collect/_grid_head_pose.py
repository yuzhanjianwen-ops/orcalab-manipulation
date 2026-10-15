# -*- coding: utf-8 -*-
"""三维网格搜索：解出 camera_head 的**真实渲染位姿**。

固定朝向 = 报告朝向，位置 = 报告位置 + Δ，Δ 在 ±0.6 m 立方网格上取值，
逐点渲染并与编辑器屏幕(idx1)画面比相关性，取最大者，再局部细化。

为什么怀疑 Δ：机器人 actor `/dual_arm_collaborative_service_robot_1` 的 scale = 1.6954，
而机载相机的世界位姿里这个 scale 可能没被乘进相机偏移里 → 相机落在头部外壳内部。

产出： _fov_probe/headGrid/  +  head_grid_best.png / report.txt
"""
import os
import sys
import io
import json
import time
import base64
import itertools
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageDraw, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "headGrid")
os.makedirs(OUT, exist_ok=True)

P0 = np.array([18.057, -3.3775, 2.1156])
ROT = [-29.142, -0.114, 90.364]
ROBOT_P = np.array([18.464, -3.3896, 0.0383])       # /dual_arm_collaborative_service_robot_1
ROBOT_S = 1.695356845855713

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


def center_sq(im, n=110):
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


NIDX = itertools.count(900)


def render(pos):
    i = next(NIDX)
    r = m.call("get_view_png_from_transform",
               {"position": [float(x) for x in pos], "rotation": list(ROT), "index": i},
               timeout=90)
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
refv = center_sq(ref)
say("参考画面 idx1 尺寸:", ref.size)

say("")
say("几何提示：robot_p=%s  robot_scale=%.4f" % (list(ROBOT_P), ROBOT_S))
d = P0 - ROBOT_P
say("报告位置相对机器人原点 d=%s  |d|=%.3f" % ([round(x, 3) for x in d], float(np.linalg.norm(d))))
for tag, p in (("(scale-1)*d 补正", ROBOT_P + ROBOT_S * d),
               ("d/scale 反向补正", ROBOT_P + d / ROBOT_S)):
    say("  %s -> %s" % (tag, [round(float(x), 3) for x in p]))


def sweep(vals, tag):
    t0 = time.time()
    rows = []
    for dx, dy, dz in vals:
        pos = P0 + np.array([dx, dy, dz])
        img = render(pos)
        if img is None:
            continue
        v = center_sq(img)
        c = float(np.corrcoef(refv.ravel(), v.ravel())[0, 1])
        rows.append((c, (dx, dy, dz), pos, img))
    rows.sort(key=lambda r: -r[0])
    dt = (time.time() - t0) / max(1, len(vals))
    say("[%s] 渲染 %d 张，%.2f s/张" % (tag, len(vals), dt))
    for c, off, pos, _ in rows[:8]:
        say("   corr=%.3f  Δ=(%+.2f,%+.2f,%+.2f)  pos=%s" % (
            c, off[0], off[1], off[2], [round(float(x), 3) for x in pos]))
    return rows


base = [-0.6, -0.3, 0.0, 0.3, 0.6]
coarse = list(itertools.product(base, base, base))
say("")
say("=== 粗搜 5^3=125 点 ===")
rows = sweep(coarse, "coarse")
best = rows[0]

# 局部细化：以最优点为中心 ±0.12，步长 0.06
bx, by, bz = best[1]
fine = [(bx + i * 0.06, by + j * 0.06, bz + k * 0.06)
        for i in (-2, -1, 0, 1, 2) for j in (-2, -1, 0, 1, 2) for k in (-2, -1, 0, 1, 2)]
say("")
say("=== 细搜 5^3=125 点（绕最优 Δ） ===")
rows2 = sweep(fine, "fine")
best2 = rows2[0]

allrows = rows + rows2
allrows.sort(key=lambda r: -r[0])
say("")
say("=" * 70)
say("最佳 Δ=(%+.3f,%+.3f,%+.3f)  corr=%.3f" % (best2[1][0], best2[1][1], best2[1][2], best2[0]))
say("最佳渲染位置 = %s" % [round(float(x), 4) for x in best2[2]])
dev = best2[2] - P0
say("相对报告位置偏移 Δ = %s  |Δ|=%.4f m" % ([round(float(x), 4) for x in dev], float(np.linalg.norm(dev))))
k = float(np.linalg.norm(dev) / np.linalg.norm(d))
say("|Δ| / |d| = %.4f   (1.6954-1=0.6954 ; 1-1/1.6954=0.4102)" % k)
for tag, p in (("(scale-1)*d 补正", ROBOT_P + ROBOT_S * d),
               ("d/scale 反向补正", ROBOT_P + d / ROBOT_S)):
    say("  与 %s 的距离 = %.4f m" % (tag, float(np.linalg.norm(p - best2[2]))))
say("=" * 70)

best2[3].save(os.path.join(OUT, "head_grid_best.png"))

# 最佳点 + 参考 并排
GAP, LAB, TH = 10, 28, 420
W = TH * 2 + GAP * 3
H = 24 + LAB + TH + GAP
M = Image.new("RGB", (W, H), (14, 14, 16))
dr = ImageDraw.Draw(M)
dr.text((GAP, 6), "左: 编辑器屏幕 idx1（目标构图）   右: 修正 Δ 后引擎渲染（最佳网格点）", fill=(255, 220, 0))
for i, (t, im) in enumerate((("编辑器屏幕 idx1", ref), ("引擎渲染 Δ=(%+.2f,%+.2f,%+.2f)" % best2[1], best2[3]))):
    dr.text((GAP + i * (TH + GAP), 26), t, fill=(0, 255, 140))
    M.paste(im.resize((TH, TH), Image.LANCZOS), (GAP + i * (TH + GAP), 24 + LAB))
o = os.path.join(OUT, "head_grid_best.png")
M.save(o)
say("saved", o, M.size)

with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as f:
    json.dump([{"corr": c, "delta": list(off), "pos": [float(x) for x in pos]}
               for c, off, pos, _ in allrows[:60]], f, ensure_ascii=False, indent=2)
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE", OUT)
