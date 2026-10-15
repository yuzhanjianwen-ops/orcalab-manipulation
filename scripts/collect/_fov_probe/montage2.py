# -*- coding: utf-8 -*-
import os, io, sys
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe"
vp = Image.open(r"C:\Users\86322\.orcalab\viewport_image\color\AgentCamera_color_0.png").convert("RGB")
hd = Image.open(os.path.join(D, "stream_head.png")).convert("RGB")
lf = Image.open(os.path.join(D, "stream_left.png")).convert("RGB")
rt = Image.open(os.path.join(D, "stream_right.png")).convert("RGB")

TH = 420
def fit(im, th=TH):
    w, h = im.size
    return im.resize((int(w * th / h), th), Image.LANCZOS)

vp2, hd2, lf2, rt2 = fit(vp), fit(hd), fit(lf), fit(rt)
gap, lab, head = 10, 22, 30
W = vp2.width + hd2.width + gap * 3
H = head + lab + TH + 40
M = Image.new("RGB", (W, H), (18, 18, 18))
d = ImageDraw.Draw(M)
d.text((gap, 6), "VIEWPORT (what you click in software, AgentCamera)   vs   STREAM (what collect.py records)", fill=(255, 220, 0))
x = gap
d.text((x, head), "viewport 1080x1080 (square)", fill=(0, 255, 128)); M.paste(vp2, (x, head + lab)); x += vp2.width + gap
d.text((x, head), "camera_head 640x480", fill=(0, 255, 128)); M.paste(hd2, (x, head + lab)); x += hd2.width + gap
d.text((x, head), "camera_left 640x480", fill=(0, 255, 128)); M.paste(lf2, (x, head + lab)); x += lf2.width + gap
d.text((x, head), "camera_right 640x480", fill=(0, 255, 128)); M.paste(rt2, (x, head + lab))
out = os.path.join(D, "viewport_vs_stream.png")
M.save(out)
print("saved", out, M.size)