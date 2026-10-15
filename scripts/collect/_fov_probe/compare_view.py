# -*- coding: utf-8 -*-
"""对比：软件视口图(AgentCamera) vs 三路推流图(camera_head/left/right)。"""
import os, sys, io, time, json
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import orca_boot  # noqa
import numpy as np
from PIL import Image
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
from official_camera import OfficialCameraFeed
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe")
os.makedirs(OUT, exist_ok=True)

# ---- 1) 抓软件视口图 ----
m = OrcaMcp(); m.connect()
info = json.loads(call_text(m, "get_viewport_camera_info"))
print("viewport transform:", info["transform"])
vp = info["color_path"]
print("viewport png:", vp, os.path.exists(vp))

# ---- 2) 抓三路推流 ----
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["cmp"], time_step=0.001, render_mode="force")
env.initialize_grpc(); env.initialize_simulation()
env.set_sync_render(False); env.set_render_fps(30)
feed = OfficialCameraFeed(first_frame_timeout=20.0)
print("feed.open:", feed.open(env), feed.error)
idx = [-1]
def drive():
    env.do_simulation(np.zeros(env.model.nu, dtype=np.float32), 20)
    idx[0] += 1
    env.render(simulate_index=idx[0], request_idr=(idx[0] == 0))
t = time.time() + 4
while time.time() < t:
    drive(); feed._tick(); time.sleep(1/30)
time.sleep(0.4); feed._tick()
fr = feed.grab_multi()
for k, v in fr.items():
    if v is not None:
        fp = os.path.join(OUT, "stream_%s.png" % k)
        Image.fromarray(v).save(fp)
        print("stream %-6s %sx%s mean=%.1f" % (k, v.shape[1], v.shape[0], v.mean()))
# ---- 3) 也抓一张"相机机位重放图" ----
try:
    tf = json.loads(call_text(m, "get_actor_transform", {"actor_name": "/dual_arm_collaborative_service_robot_1"}))
    print("robot transform:", tf)
except Exception as e:
    print("robot transform err", e)
feed.close(); env.close()
print("DONE")