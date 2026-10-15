# -*- coding: utf-8 -*-
import os, io, sys
import numpy as np
from PIL import Image
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe"
vp = Image.open(os.path.join(D, "viewport_cams", "cam1.png")).convert("L")
st = Image.open(os.path.join(D, "stream_head.png")).convert("L")
S = 200
vpa = np.asarray(vp.resize((S, S), Image.LANCZOS), dtype=np.float32)
sta_full = np.asarray(st, dtype=np.float32)
def resize_np(a, w, h):
    return np.asarray(Image.fromarray(a.astype(np.uint8)).resize((w, h), Image.LANCZOS), dtype=np.float32)
best = []
for f in np.arange(0.60, 1.45, 0.03):   # stream horizontal crop factor
    w = int(640 * f)
    if w < 20: continue
    x0 = (640 - w) // 2
    crop = resize_np(sta_full[:, x0:x0+w], S, S)
    a = vpa - vpa.mean(); b = crop - crop.mean()
    denom = (np.sqrt((a*a).sum()) * np.sqrt((b*b).sum()))
    ncc = float((a*b).sum() / denom) if denom > 0 else 0
    best.append((ncc, f))
best.sort(reverse=True)
print("top-5 horizontal crop factor (NCC):")
for ncc, f in best[:5]:
    print("   factor=%.2f  hfov_stream=%.1f  NCC=%.3f" % (f, 2*np.degrees(np.arctan((640*f/480)*np.tan(np.radians(45)))), ncc))