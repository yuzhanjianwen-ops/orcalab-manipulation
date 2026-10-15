# -*- coding: utf-8 -*-
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\epframes"
h = np.asarray(Image.open(os.path.join(D,"head_0.png")).convert("RGB"), dtype=np.float64)
l = np.asarray(Image.open(os.path.join(D,"left_0.png")).convert("RGB"), dtype=np.float64)
r = np.asarray(Image.open(os.path.join(D,"right_0.png")).convert("RGB"), dtype=np.float64)
print("shapes", h.shape, l.shape, r.shape)
print("mean per cam: head %.2f left %.2f right %.2f" % (h.mean(), l.mean(), r.mean()))
print("head vs left  mean|diff| = %.2f" % np.abs(h-l).mean())
print("head vs right mean|diff| = %.2f" % np.abs(h-r).mean())
print("left vs right mean|diff| = %.2f" % np.abs(l-r).mean())
# dynamic range within an image
for nm, a in [("head",h),("left",l),("right",r)]:
    print("%-6s min=%.0f max=%.0f std=%.2f unique_gray=%d" % (nm, a.min(), a.max(), a.std(), len(np.unique(a.astype(np.uint8)[:,:,0]))))