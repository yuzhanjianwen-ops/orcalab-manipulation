# -*- coding: utf-8 -*-
"""比对 vpmap：gl_idx0..5(编辑器视口) vs 三路机载推流 vs agent_idx0..5。并拼蒙太奇。"""
import os, sys, io, json
import numpy as np
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

V = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\vpmap"
S = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\same"
SZ = 256


def cv(im):
    return np.asarray(im.convert("L").resize((SZ, SZ), Image.LANCZOS), dtype=np.float32)


def ncc(p, q):
    p = p - p.mean(); q = q - q.mean()
    d = np.sqrt((p * p).sum()) * np.sqrt((q * q).sum())
    return float((p * q).sum() / d) if d > 0 else 0.0


streams = {}
for name in ("head", "left", "right"):
    p = os.path.join(S, "stream_%s.png" % name)
    if os.path.exists(p):
        streams[name] = cv(Image.open(p))

print("=== 编辑器视口(gl_idxN) vs 三路机载推流 ===")
print("  idx |   head    left   right  | best")
for i in range(6):
    p = os.path.join(V, "gl_idx%d.png" % i)
    if not os.path.exists(p):
        continue
    g = cv(Image.open(p))
    row = {k: ncc(g, v) for k, v in streams.items()}
    best = max(row, key=row.get)
    print("   %d  | %6.3f  %6.3f  %6.3f | %s (%.3f)" % (
        i, row.get("head", 0), row.get("left", 0), row.get("right", 0), best, row[best]))

print("\n=== 编辑器视口(gl_idxN) vs 同 index 的 AgentCamera ===")
for i in range(6):
    p = os.path.join(V, "gl_idx%d.png" % i)
    q = os.path.join(V, "agent_idx%d.png" % i)
    if os.path.exists(p) and os.path.exists(q):
        print("   idx %d  NCC=%.3f" % (i, ncc(cv(Image.open(p)), cv(Image.open(q)))))

# ---------- 蒙太奇 ----------
poses = {}
pp = os.path.join(V, "poses.json")
if os.path.exists(pp):
    poses = json.load(open(pp, encoding="utf-8"))

TH = 300


def fit(im, th=TH):
    w, h = im.size
    return im.resize((max(1, int(w * th / h)), th), Image.LANCZOS)


tiles = []
for i in range(6):
    p = os.path.join(V, "gl_idx%d.png" % i)
    if os.path.exists(p):
        t = poses.get(str(i), {})
        pos = ",".join("%.2f" % x for x in t.get("position", []))
        tiles.append(("idx%d  pos[%s] scale=%.2f" % (i, pos, t.get("scale", -1)), fit(Image.open(p))))

gap, lab, hh = 10, 20, 30
cols, rows = 3, 2
W = cols * tiles[0][1].width + gap * (cols + 1)
H = hh + rows * (TH + lab) + gap * (rows + 1)
M = Image.new("RGB", (W, H), (16, 16, 16))
d = ImageDraw.Draw(M)
d.text((gap, 6), "Editor viewport after set_viewport_camera(index=0..5)  -- what the software shows for each index",
       fill=(255, 220, 0))
k = 0
for r in range(rows):
    for c in range(cols):
        if k >= len(tiles):
            break
        x = gap + c * (tiles[0][1].width + gap)
        y = hh + gap + r * (TH + lab)
        d.text((x + 2, y), tiles[k][0], fill=(0, 255, 128))
        M.paste(tiles[k][1], (x, y + lab))
        k += 1
out = os.path.join(V, "gl_indices_montage.png")
M.save(out)
print("\nsaved", out, M.size)
