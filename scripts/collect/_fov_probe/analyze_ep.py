# -*- coding: utf-8 -*-
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
try:
    import av
except Exception as e:
    print("no av:", e); raise SystemExit

ROOT = r"D:\data\lerobot\pick_medbox"
# pick the newest episode dir that has all three videos
cands = []
for d in sorted(os.listdir(ROOT)):
    base = os.path.join(ROOT, d, "videos")
    if not os.path.isdir(base): continue
    cams = {}
    for c in os.listdir(base):
        p = os.path.join(base, c, "chunk-000", "file-000.mp4")
        if os.path.exists(p): cams[c] = p
    if len(cams) >= 2:
        cands.append((d, cams))
print("episodes with videos:", [c[0] for c in cands])
ep, cams = cands[-1]
print("using episode:", ep, "cams:", list(cams))
info = json.load(open(os.path.join(ROOT, ep, "meta", "info.json"), encoding="utf-8"))
print("info: fps=%s total_episodes=%s total_frames=%s" % (info.get("fps"), info.get("total_episodes"), info.get("total_frames")))
print("features:", list(info.get("features", {}).keys()))

for cam, path in sorted(cams.items()):
    c = av.open(path)
    frames = []
    for f in c.decode(video=0):
        frames.append(f.to_ndarray(format="rgb24"))
    c.close()
    n = len(frames)
    if n < 2:
        print("%-28s frames=%d (too few)" % (cam, n)); continue
    diffs = []
    for i in range(1, n):
        a = frames[i-1].astype(np.int16); b = frames[i].astype(np.int16)
        diffs.append(float(np.abs(a-b).mean()))
    diffs = np.array(diffs)
    # also range of pixel means
    means = np.array([fr.mean() for fr in frames])
    print("%-28s frames=%3d  shape=%s  frame-to-frame diff: mean=%.2f max=%.2f  changed(>1)=%d/%d  bright: min=%.1f max=%.1f" % (
        cam, n, frames[0].shape, diffs.mean(), diffs.max(), int((diffs>1).sum()), len(diffs), means.min(), means.max()))