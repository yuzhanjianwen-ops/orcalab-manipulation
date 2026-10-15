# -*- coding: utf-8 -*-
import os, sys, io, hashlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np, av
EP = r"D:\data\lerobot\pick_medbox\20261011_175243"
for cam in ["head", "left", "right"]:
    p = os.path.join(EP, "videos", "observation.images.%s" % cam, "chunk-000", "file-000.mp4")
    c = av.open(p)
    hashes = []
    prev = None
    dup = 0
    maxjump = 0
    arrs = []
    for f in c.decode(video=0):
        a = f.to_ndarray(format="rgb24")
        arrs.append(a)
    c.close()
    for i in range(1, len(arrs)):
        d = float(np.abs(arrs[i].astype(np.int16) - arrs[i-1].astype(np.int16)).mean())
        if d < 0.05: dup += 1
        maxjump = max(maxjump, d)
    # byte-identical consecutive
    ident = sum(1 for i in range(1,len(arrs)) if np.array_equal(arrs[i], arrs[i-1]))
    print("%-6s frames=%d  consecutive byte-identical=%d  near-dup(<0.05)=%d  max frame-to-frame diff=%.2f" % (
        cam, len(arrs), ident, dup, maxjump))
    # spread over whole episode
    if len(arrs) > 10:
        spread = float(np.abs(arrs[0].astype(np.int16) - arrs[-1].astype(np.int16)).mean())
        print("       first-vs-last diff = %.2f" % spread)