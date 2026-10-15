# -*- coding: utf-8 -*-
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np, av
ROOT = r"D:\data\lerobot\pick_medbox"
print("%-20s %-10s %-24s %s" % ("episode", "cam", "resolution", "frozen?"))
for ep in sorted(os.listdir(ROOT)):
    vd = os.path.join(ROOT, ep, "videos")
    if not os.path.isdir(vd): continue
    for cam in ["head", "left", "right"]:
        p = os.path.join(vd, "observation.images.%s" % cam, "chunk-000", "file-000.mp4")
        if not os.path.exists(p): continue
        c = av.open(p); arrs = [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]; c.close()
        if len(arrs) < 3:
            print("%-20s %-10s %-24s %s" % (ep, cam, "%dx%d" % (arrs[0].shape[1], arrs[0].shape[0]) if arrs else "?", "n<3")); continue
        d = np.array([float(np.abs(arrs[i].astype(np.int16)-arrs[i-1].astype(np.int16)).mean()) for i in range(1,len(arrs))])
        ident = sum(1 for i in range(1,len(arrs)) if np.array_equal(arrs[i], arrs[i-1]))
        print("%-20s %-10s %-24s frames=%d ident=%d mean|d|=%.2f %s" % (
            ep, cam, "%dx%d" % (arrs[0].shape[1], arrs[0].shape[0]), len(arrs), ident, d.mean(),
            "FROZEN" if d.mean() < 1.0 else ("weak" if d.mean() < 3 else "ok")))