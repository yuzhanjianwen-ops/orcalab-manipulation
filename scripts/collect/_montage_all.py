# -*- coding: utf-8 -*-
import os, io, sys
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\same"

editor = Image.open(os.path.join(D, "_gl_crop.png")).convert("RGB")
head = Image.open(os.path.join(D, "stream_head.png")).convert("RGB")
left = Image.open(os.path.join(D, "stream_left.png")).convert("RGB")
right = Image.open(os.path.join(D, "stream_right.png")).convert("RGB")
agent = Image.open(os.path.join(D, "agent_camera.png")).convert("RGB")

TH = 360


def fit(im, th=TH):
    w, h = im.size
    return im.resize((max(1, int(w * th / h)), th), Image.LANCZOS)


tiles = [
    ("A. EDITOR viewport 1204x1008  (what YOU see in the software)", fit(editor)),
    ("B. agent_camera 1080x1080  (MCP offscreen render)", fit(agent)),
    ("C. stream_head 640x480  (robot onboard, ws 7070)", fit(head)),
    ("D. stream_left 640x480  (robot onboard, ws 7080)", fit(left)),
    ("E. stream_right 640x480  (robot onboard, ws 7090)", fit(right)),
]

# 两行布局：上排 A/B，下排 C/D/E
gap, lab, head_h = 12, 22, 34
row1 = tiles[:2]
row2 = tiles[2:]
w1 = sum(t[1].width for t in row1) + gap * (len(row1) + 1)
w2 = sum(t[1].width for t in row2) + gap * (len(row2) + 1)
W = max(w1, w2)
H = head_h + gap + (TH + lab) * 2 + gap * 2
M = Image.new("RGB", (W, H), (16, 16, 16))
d = ImageDraw.Draw(M)
d.text((gap, 8), "SAME moment  |  WHY the captured image != the editor window  (res / aspect / camera differ)",
       fill=(255, 220, 0))

y = head_h + gap
for row in (row1, row2):
    x = gap
    for lab_txt, im in row:
        d.text((x + 2, y), lab_txt, fill=(0, 255, 128))
        M.paste(im, (x, y + lab))
        x += im.width + gap
    y += TH + lab + gap

out = os.path.join(D, "compare_all.png")
M.save(out)
print("saved", out, M.size)
