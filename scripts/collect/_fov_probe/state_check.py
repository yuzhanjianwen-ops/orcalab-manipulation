# -*- coding: utf-8 -*-
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np, pyarrow.parquet as pq
EP = r"D:\data\lerobot\pick_medbox\20261011_175243"
t = pq.read_table(os.path.join(EP, "data", "chunk-000", "file-000.parquet"))
st = np.array(t.column("observation.state").to_pylist(), dtype=np.float64)
ac = np.array(t.column("action").to_pylist(), dtype=np.float64)
print("state", st.shape, "action", ac.shape)
rng = st.max(axis=0) - st.min(axis=0)
print("\nstate per-dim total range over whole episode (44 dims):")
print(np.round(rng, 4))
print("\nnum dims that never change (range==0): %d / %d" % (int((rng < 1e-9).sum()), len(rng)))
print("num dims with range > 0.05: %d" % int((rng > 0.05).sum()))
arng = ac.max(axis=0) - ac.min(axis=0)
print("\naction per-dim range (8 dims):", np.round(arng, 4))
print("\nsample state[0] vs state[200]:")
print("  s0  =", np.round(st[0], 3))
print("  s200=", np.round(st[200], 3))
print("\nunique rows in state:", len(np.unique(st, axis=0)), "of", len(st))