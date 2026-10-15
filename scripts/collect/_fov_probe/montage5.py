# -*- coding: utf-8 -*-
import os, io, sys
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\cmp2"
imgs = [
    ("A. your editor window (GL viewport, 1204x1008)", os.path.join(D, "A_editor_window.png")),
    ("B. MCP get_viewport_png (AgentCamera, 1080x1080)", os.path.join(D, "B_mcp_viewport.png")),
    ("C. camera_head WebSocket stream (640x480)", r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\stream_head.png"),
]
TH = 430
def fit(im, th=TH):
    w, h = im.size; return im.resize((int(w*th/h), th), Image.LANCZOS)
tiles = [(lab, fit(Image.open(p).convert("RGB"))) for lab, p in imgs]
gap, LAB = 10, 22
W = sum(t[1].width for t in tiles) + gap*(len(tiles)+1)
H = TH + LAB + gap*2 + 20
M = Image.new("RGB", (W, H), (18,18,18)); d = ImageDraw.Draw(M)
d.text((gap, 5), "THREE DIFFERENT RENDER PATHS - same robot, same scene", fill=(255,220,0))
x = gap
for lab, im in tiles:
    d.text((x, 20), lab, fill=(0,255,128))
    M.paste(im, (x, 20+LAB))
    x += im.width + gap
out = os.path.join(D, "three_paths.png")
M.save(out); print("saved", out, M.size)