# -*- coding: utf-8 -*-
import os, io, sys, glob
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\avs"
TH = 300


def fit(im, th=TH):
    w, h = im.size
    return im.resize((max(1, int(w * th / h)), th), Image.LANCZOS)


tiles = []
for i in range(6):
    p = os.path.join(D, "agent_vp%d.png" % i)
    if os.path.exists(p):
        tiles.append(("AgentCamera @ viewport idx%d  (1080x1080)" % i, fit(Image.open(p).convert("RGB"))))
for name in ("head", "left", "right"):
    p = os.path.join(D, "vp1_stream_%s.png" % name)
    if os.path.exists(p):
        tiles.append(("stream_%s  (640x480)" % name, fit(Image.open(p).convert("RGB"))))

gap, lab, hh = 10, 20, 30
cols, rows = 3, 3
W = cols * tiles[0][1].width + gap * (cols + 1)
H = hh + rows * (TH + lab) + gap * (rows + 1)
M = Image.new("RGB", (W, H), (16, 16, 16))
d = ImageDraw.Draw(M)
d.text((gap, 6), "AgentCamera render for viewport index 0..5   vs   onboard streams (same moment)", fill=(255, 220, 0))
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
out = os.path.join(D, "agent_vs_stream_montage.png")
M.save(out)
print("saved", out, M.size)
