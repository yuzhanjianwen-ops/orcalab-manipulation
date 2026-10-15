# -*- coding: utf-8 -*-
"""决定性实验：手臂真的动时，腕相机画面变不变？"""
import os, sys, io, time
sys.path.insert(0, r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import orca_boot  # noqa
import numpy as np
from PIL import Image
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
from official_camera import OfficialCameraFeed

OUT = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\move_test"
os.makedirs(OUT, exist_ok=True)
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["mv"], time_step=0.001, render_mode="force")
env.initialize_grpc(); env.initialize_simulation()
env.set_sync_render(False); env.set_render_fps(30)
m = env.model
feed = OfficialCameraFeed(first_frame_timeout=20.0)
print("open:", feed.open(env), feed.error)
idx = [-1]
def step(ctrl):
    env.do_simulation(ctrl, 20)
    idx[0] += 1
    env.render(simulate_index=idx[0], request_idr=(idx[0] == 0))
def warm(ctrl, n):
    for _ in range(n):
        step(ctrl); feed._tick(); time.sleep(1/30)
    time.sleep(0.3); feed._tick()

ctrl0 = np.zeros(m.nu, dtype=np.float32)
warm(ctrl0, 40)
f0 = feed.grab_multi()
for k, v in f0.items():
    if v is not None: Image.fromarray(v).save(os.path.join(OUT, "before_%s.png" % k))
print("baseline captured:", {k: (None if v is None else v.shape) for k, v in f0.items()})

# idx 20..26 = arm_r_joint1..7 (mctrl). Move joint2 (idx 21) and joint4 (idx 23) a lot.
ctrl1 = ctrl0.copy()
ctrl1[21] = 0.8    # arm_r_joint2
ctrl1[23] = -0.6   # arm_r_joint4
ctrl1[25] = 0.5    # arm_r_joint6
warm(ctrl1, 120)
f1 = feed.grab_multi()
for k, v in f1.items():
    if v is not None: Image.fromarray(v).save(os.path.join(OUT, "after_%s.png" % k))

print("\nframe change BEFORE vs AFTER arm motion:")
for k, v in f1.items():
    if v is None or f0.get(k) is None:
        print("  %-6s missing" % k); continue
    d = float(np.abs(v.astype(np.int16) - f0[k].astype(np.int16)).mean())
    print("  %-6s mean|diff| = %6.2f   %s" % (k, d, "CHANGED" if d > 1 else "NO CHANGE(!)"))

feed.close(); env.close()
print("saved to", OUT)