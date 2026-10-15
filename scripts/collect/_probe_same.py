# -*- coding: utf-8 -*-
"""同一时刻抓齐：编辑器窗口 / camera_head|left|right 推流 / 离屏 AgentCamera。
仿真暂停(Sim 0Hz)时位姿冻结，因此差异只可能来自"相机+配置"，与时间无关。
产出： _fov_probe/same/
"""
import os, sys, io, time, json, ctypes, shutil
from ctypes import wintypes
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import orca_boot  # noqa: F401
import numpy as np
from PIL import Image, ImageGrab
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
from official_camera import OfficialCameraFeed

OUT = os.path.join(HERE, "_fov_probe", "same")
os.makedirs(OUT, exist_ok=True)

# ---------- 1) 真实的编辑器窗口 ----------
u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
hw = []


def cb(h, l):
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if not u.IsWindowVisible(h):
        return True
    n = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, n, 512)
    if n.value.strip().startswith("26.8.1"):
        hw.append(h)
    return True


u.EnumWindows(CB(cb), None)
print("orca windows:", hw)
win_img = None
if hw:
    h = hw[0]
    try:
        u.ShowWindow(h, 9)
        u.SetForegroundWindow(h)
        time.sleep(0.8)
    except Exception as e:
        print("focus err", e)
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    win_img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
    win_img.save(os.path.join(OUT, "editor_window.png"))
    print("editor_window %dx%d" % win_img.size)

# ---------- 2) 三路推流 ----------
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["same"], time_step=0.001, render_mode="force")
env.initialize_grpc()
env.initialize_simulation()
env.set_sync_render(False)
env.set_render_fps(30)
print("registered cameras:", list(env.get_camera_names()))

feed = OfficialCameraFeed(first_frame_timeout=20.0)
print("feed.open ->", feed.open(env), "|", feed.error)
idx = [-1]


def drive():
    env.do_simulation(np.zeros(env.model.nu, dtype=np.float32), 1)
    idx[0] += 1
    env.render(simulate_index=idx[0], request_idr=(idx[0] == 0))


t = time.time() + 4
while time.time() < t:
    drive()
    feed._tick()
    time.sleep(1 / 30)
time.sleep(0.4)
feed._tick()
fr = feed.grab_multi()
for k, v in fr.items():
    if v is not None:
        fp = os.path.join(OUT, "stream_%s.png" % k)
        Image.fromarray(v).save(fp)
        print("stream %-6s %sx%s mean=%.1f" % (k, v.shape[1], v.shape[0], v.mean()))

# ---------- 3) 离屏 AgentCamera ----------
ap = r"C:\Users\86322\.orcalab\viewport_image\color\AgentCamera_color_0.png"
if os.path.exists(ap):
    try:
        shutil.copy(ap, os.path.join(OUT, "agent_camera.png"))
        print("agent_camera", Image.open(ap).size)
    except Exception as e:
        print("agent copy err", e)

feed.close()
env.close()
print("DONE")
