# -*- coding: utf-8 -*-
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np, av
from PIL import Image

EP = r"D:\data\lerobot\pick_medbox\20261011_175243"
# 1) state 变化
try:
    import pyarrow.parquet as pq
    t = pq.read_table(os.path.join(EP, "data", "chunk-000", "file-000.parquet"))
    st = np.array(t.column("observation.state").to_pylist(), dtype=np.float64)
    ac = np.array(t.column("action").to_pylist(), dtype=np.float64)
    print("state shape", st.shape, " action shape", ac.shape)
    d = np.abs(np.diff(st, axis=0)).mean(axis=0)
    print("state per-dim mean|delta| (first 20):", np.round(d[:20], 4))
    print("state overall movement: mean=%.4f max=%.4f" % (d.mean(), d.max()))
    print("action per-dim mean|delta| (first 10):", np.round(np.abs(np.diff(ac,axis=0)).mean(axis=0)[:10],4))
except Exception as e:
    print("parquet err:", type(e).__name__, e)

# 2) 抽帧图：head 在 0/25/50/75/100%
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fov_probe", "epframes")
os.makedirs(D, exist_ok=True)
for cam in ["head", "left", "right"]:
    p = os.path.join(EP, "videos", "observation.images.%s" % cam, "chunk-000", "file-000.mp4")
    c = av.open(p); frames = [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]; c.close()
    idx = [0, len(frames)//4, len(frames)//2, 3*len(frames)//4, len(frames)-1]
    for k, i in enumerate(idx):
        Image.fromarray(frames[i]).save(os.path.join(D, "%s_%d.png" % (cam, k)))
    print(cam, "frames", len(frames), "sampled idx", idx, "size", frames[0].shape)