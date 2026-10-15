# -*- coding: utf-8 -*-
"""把编辑器窗口的 GL 视口区域与各路候选做数值匹配，判断编辑器显示的是哪台相机。"""
import os, sys, io
import numpy as np
from PIL import Image
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\same"
win = Image.open(os.path.join(D, "editor_window.png")).convert("RGB")
W, H = win.size
print("editor window size:", W, H)
a = np.asarray(win, dtype=np.float32)

# ---- 自动找左侧面板右边界（列标准差跳变）----
col_std = a.std(axis=(0, 2))
# 面板是均匀深灰，std 很低
smooth = np.convolve(col_std, np.ones(15) / 15, mode="same")
# 从左边找第一处 std 明显升高的位置
thr = max(6.0, smooth.max() * 0.25)
x0 = int(np.argmax(smooth > thr))
# ---- 找顶部工具栏下边界 ----
row_std = a.std(axis=(1, 2))
smooth_r = np.convolve(row_std, np.ones(9) / 9, mode="same")
y0 = int(np.argmax(smooth_r > thr))
print("detected GL region origin: x0=%d y0=%d  (region %dx%d)" % (x0, y0, W - x0, H - y0))

gl = win.crop((x0, y0, W, H))
gl.save(os.path.join(D, "_gl_crop.png"))
print("GL crop:", gl.size, "aspect=%.3f" % (gl.size[0] / gl.size[1]))

S = 256


def cv(im):
    return np.asarray(im.convert("L").resize((S, S), Image.LANCZOS), dtype=np.float32)


def ncc(p, q):
    p = p - p.mean(); q = q - q.mean()
    d = (np.sqrt((p * p).sum()) * np.sqrt((q * q).sum()))
    return float((p * q).sum() / d) if d > 0 else 0.0


g = cv(gl)
print("\n=== 与编辑器视口的匹配度 (NCC, 越高越像) ===")
cands = [("stream_head", "stream_head.png"), ("stream_left", "stream_left.png"),
         ("stream_right", "stream_right.png"), ("agent_camera", "agent_camera.png"),
         ("_gl_crop", "_gl_crop.png")]
res = []
for name, fn in cands:
    p = os.path.join(D, fn)
    if not os.path.exists(p):
        continue
    im = Image.open(p)
    n = ncc(g, cv(im))
    res.append((n, name, im.size))
for n, name, sz in sorted(res, reverse=True):
    print("  %-14s %-11s NCC=%.3f" % (name, "%dx%d" % sz, n))

# 也对原始几张推流做横向裁剪搜索，排除宽高比干扰
print("\n=== 横向裁剪搜索（把候选横向裁到与编辑器同宽高比再比）===")
target_ar = gl.size[0] / gl.size[1]
for name, fn in [("stream_head", "stream_head.png"), ("stream_left", "stream_left.png"),
                 ("stream_right", "stream_right.png")]:
    p = os.path.join(D, fn)
    if not os.path.exists(p):
        continue
    src = Image.open(p)
    w, h = src.size
    best = None
    for f in np.arange(0.5, 1.001, 0.05):
        cw = int(w * f)
        x0c = (w - cw) // 2
        crop = src.crop((x0c, 0, x0c + cw, h))
        n = ncc(g, cv(crop))
        if best is None or n > best[0]:
            best = (n, f)
    print("  %-14s best NCC=%.3f  (h-crop factor %.2f)" % (name, best[0], best[1]))
