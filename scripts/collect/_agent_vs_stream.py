# -*- coding: utf-8 -*-
"""可靠通道：把软件视口切到 index=N，读离屏 AgentCamera（=软件视口当前相机渲染），
同一时刻抓三路机载推流，比较"软件视口相机"与"机载相机"是否同一台。
产出： _fov_probe/avs/
"""
import os, sys, io, time, json, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import orca_boot  # noqa
import numpy as np
from PIL import Image
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
from official_camera import OfficialCameraFeed
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "avs")
os.makedirs(OUT, exist_ok=True)
AP = r"C:\Users\86322\.orcalab\viewport_image\color\AgentCamera_color_0.png"
SZ = 256


def cv(im):
    return np.asarray(im.convert("L").resize((SZ, SZ), Image.LANCZOS), dtype=np.float32)


def ncc(p, q):
    p = p - p.mean(); q = q - q.mean()
    d = np.sqrt((p * p).sum()) * np.sqrt((q * q).sum())
    return float((p * q).sum() / d) if d > 0 else 0.0


m = OrcaMcp()
m.connect()
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["avs"], time_step=0.001, render_mode="force")
env.initialize_grpc()
env.initialize_simulation()
env.set_sync_render(False)
env.set_render_fps(30)
feed = OfficialCameraFeed(first_frame_timeout=20.0)
print("feed.open ->", feed.open(env), "|", feed.error)
idx = [-1]


def drive():
    env.do_simulation(np.zeros(env.model.nu, dtype=np.float32), 1)
    idx[0] += 1
    env.render(simulate_index=idx[0], request_idr=(idx[0] == 0))


def pump(sec=1.5):
    t = time.time() + sec
    while time.time() < t:
        drive()
        feed._tick()
        time.sleep(1 / 30)
    time.sleep(0.3)
    feed._tick()


for vi in range(6):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": vi})
    except Exception as e:
        print("idx", vi, "set err", str(e)[:80])
    time.sleep(1.0)
    try:
        tr = json.loads(call_text(m, "get_viewport_transform", {}))
        tr = tr.get("transform", tr)
        pos = [round(x, 3) for x in tr.get("position", [])]
        sc = tr.get("scale")
    except Exception:
        pos, sc = [], None
    pump(1.0)
    fr = feed.grab_multi()
    # 立刻读 AgentCamera
    try:
        shutil.copy(AP, os.path.join(OUT, "agent_vp%d.png" % vi))
        ag = Image.open(os.path.join(OUT, "agent_vp%d.png" % vi)).convert("RGB")
    except Exception as e:
        print("idx", vi, "agent err", e)
        ag = None
    line = "idx%d pos=%s scale=%s" % (vi, pos, sc)
    if ag is not None:
        g = cv(ag)
        for name in ("head", "left", "right"):
            v = fr.get(name)
            if v is None:
                continue
            Image.fromarray(v).save(os.path.join(OUT, "vp%d_stream_%s.png" % (vi, name)))
            line += "  | vs %s=%.3f" % (name, ncc(g, cv(Image.fromarray(v))))
    print(line)

feed.close()
env.close()
print("DONE")
