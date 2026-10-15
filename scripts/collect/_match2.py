# -*- coding: utf-8 -*-
"""用面板底色定位编辑器 3D 视口区域，再与各路候选做 NCC 匹配。"""
import os, sys, io
import numpy as np
from PIL import Image
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\same"
win = Image.open(os.path.join(D, "editor_window.png")).convert("RGB")
W, H = win.size
a = np.asarray(win, dtype=np.float32)
print("window:", W, H)

# 左上角取面板底色
panel = np.median(a[300:900, 10:60, :].reshape(-1, 3), axis=0)
print("panel color:", np.round(panel, 1))

diff = np.abs(a - panel).mean(axis=2)          # HxW
is3d = diff > 18

# 列方向：从中间往左找第一列"大量非面板"的位置
col_frac = is3d.mean(axis=0)                    # W
x0 = W
for x in range(W // 2, 0, -1):
    if col_frac[x] < 0.35 and col_frac[max(0, x - 30):x].mean() < 0.35:
        x0 = x + 1
        break
# 行方向：从下往上找第一行"大量非面板"
row_frac = is3d[:, x0:].mean(axis=1)            # H
y0 = H
for y in range(H // 2, 0, -1):
    if row_frac[y] < 0.35 and row_frac[max(0, y - 25):y].mean() < 0.35:
        y0 = y + 1
        break
print("detected GL origin x0=%d y0=%d -> region %dx%d aspect=%.3f" %
      (x0, y0, W - x0, H - y0, (W - x0) / (H - y0)))

gl = win.crop((x0, y0, W, H))
gl.save(os.path.join(D, "_gl_crop.png"))
print("GL crop:", gl.size, "aspect=%.3f" % (gl.size[0] / gl.size[1]))

S = 256


def cv(im):
    return np.asarray(im.convert("L").resize((S, S), Image.LANCZOS), dtype=np.float32)


def ncc(p, q):
    p = p - p.mean(); q = q - q.mean()
    d = np.sqrt((p * p).sum()) * np.sqrt((q * q).sum())
    return float((p * q).sum() / d) if d > 0 else 0.0


g = cv(gl)
print("\n=== NCC vs 编辑器视口 ===")
rows = []
for name, fn in [("stream_head", "stream_head.png"), ("stream_left", "stream_left.png"),
                 ("stream_right", "stream_right.png"), ("agent_camera", "agent_camera.png")]:
    p = os.path.join(D, fn)
    if not os.path.exists(p):
        continue
    im = Image.open(p)
    rows.append((ncc(g, cv(im)), name, "%dx%d" % im.size))
for n, name, sz in sorted(rows, reverse=True):
    print("  %-14s %-11s NCC=%.3f" % (name, sz, n))

print("\n=== 横向裁剪搜索 ===")
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
        xc = (w - cw) // 2
        n = ncc(g, cv(src.crop((xc, 0, xc + cw, h))))
        if best is None or n > best[0]:
            best = (n, f)
    print("  %-14s best NCC=%.3f (h-crop %.2f)" % (name, best[0], best[1]))
