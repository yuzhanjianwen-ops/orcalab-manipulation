# -*- coding: utf-8 -*-
import os, io, sys
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\viewport_cams"
labels = ["idx0 free (high/top)", "idx1 = head cam", "idx2 = right wrist cam",
          "idx3 = left wrist cam", "idx4", "idx5"]
ims = [Image.open(os.path.join(D, "cam%d.png" % i)).convert("RGB") for i in range(6)]
TH = 300
def fit(im, th=TH):
    w, h = im.size; return im.resize((int(w*th/h), th), Image.LANCZOS)
ims = [fit(i) for i in ims]
gap, lab = 8, 20
cols, rows = 3, 2
W = cols*ims[0].width + gap*(cols+1)
H = rows*(TH+lab) + gap*(rows+1) + 24
M = Image.new("RGB", (W, H), (18,18,18)); d = ImageDraw.Draw(M)
d.text((gap, 6), "OrcaStudio viewport cameras (what you click in the software)", fill=(255,220,0))
k = 0
for r in range(rows):
    for c in range(cols):
        x = gap + c*(ims[0].width+gap); y = 24 + gap + r*(TH+lab)
        d.text((x+3, y), labels[k], fill=(0,255,128))
        M.paste(ims[k], (x, y+lab)); k += 1
out = os.path.join(D, "viewport_cams_montage.png")
M.save(out); print("saved", out, M.size)