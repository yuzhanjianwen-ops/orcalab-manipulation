# -*- coding: utf-8 -*-
import os, io, sys
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\move_test"
rows = [("before", "arm at rest"), ("after", "arm MOVED")]
cams = ["head", "left", "right"]
TH = 260
def fit(im, th=TH):
    w, h = im.size; return im.resize((int(w*th/h), th), Image.LANCZOS)
gap, lab, head = 8, 20, 24
W = 3*fit(Image.open(os.path.join(D,"before_head.png"))).width + gap*4
H = head + 2*(TH+lab) + gap*3
M = Image.new("RGB", (W, H), (18,18,18)); d = ImageDraw.Draw(M)
d.text((gap,5), "CURRENT (fixed) session: does the picture change when the arm moves?", fill=(255,220,0))
colw = fit(Image.open(os.path.join(D,"before_head.png"))).width
y = head
for pre, t in rows:
    d.text((gap, y+2), t, fill=(255,255,0)); y += lab
    x = gap
    for c in cams:
        im = fit(Image.open(os.path.join(D, "%s_%s.png" % (pre, c))).convert("RGB"))
        M.paste(im, (x, y)); d.text((x+4, y+4), c, fill=(0,255,128)); x += im.width+gap
    y += TH + gap
out = os.path.join(D, "before_after.png"); M.save(out); print("saved", out, M.size)