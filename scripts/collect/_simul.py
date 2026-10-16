# -*- coding: utf-8 -*-
"""同一帧对比：把编辑器视口切到 index=N，然后"紧接着"抓机载推流，比较二者是否只是分辨率/宽高比之差。
产出： _fov_probe/simul/
"""
import os, sys, io, time, json, ctypes, shutil
from ctypes import wintypes
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import orca_boot  # noqa
import numpy as np
from PIL import Image, ImageGrab
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
from official_camera import OfficialCameraFeed
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "simul")
os.makedirs(OUT, exist_ok=True)

u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))


def find_orca():
    hw = []

    def cb(h, l):
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if not u.IsWindowVisible(h):
            return True
        n = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(h, n, 512)
        if n.value.strip().startswith("26."):
            hw.append(h)
        return True

    u.EnumWindows(CB(cb), None)
    return hw[0] if hw else None


def grab(h):
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.25)
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))


def gl_crop(im):
    W, H = im.size
    a = np.asarray(im, dtype=np.float32)
    panel = np.median(a[300:min(900, H), 10:60, :].reshape(-1, 3), axis=0)
    diff = np.abs(a - panel).mean(axis=2)
    is3d = diff > 18
    col_frac = is3d.mean(axis=0)
    x0 = W
    for x in range(W // 2, 0, -1):
        if col_frac[x] < 0.35 and col_frac[max(0, x - 30):x].mean() < 0.35:
            x0 = x + 1
            break
    row_frac = is3d[:, x0:].mean(axis=1)
    y0 = H
    for y in range(H // 2, 0, -1):
        if row_frac[y] < 0.35 and row_frac[max(0, y - 25):y].mean() < 0.35:
            y0 = y + 1
            break
    return im.crop((x0, y0, W, H))


SZ = 256


def cv(im):
    return np.asarray(im.convert("L").resize((SZ, SZ), Image.LANCZOS), dtype=np.float32)


def ncc(p, q):
    p = p - p.mean(); q = q - q.mean()
    d = np.sqrt((p * p).sum()) * np.sqrt((q * q).sum())
    return float((p * q).sum() / d) if d > 0 else 0.0


m = OrcaMcp()
m.connect()
h = find_orca()
print("hwnd:", h)

env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["simul"], time_step=0.001, render_mode="force")
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


def pump(sec=1.2):
    t = time.time() + sec
    while time.time() < t:
        drive()
        feed._tick()
        time.sleep(1 / 30)
    time.sleep(0.25)
    feed._tick()


for vi in (1, 2, 3):
    call_text(m, "set_viewport_camera", {"camera_index": vi})
    time.sleep(0.9)
    pump(1.2)
    fr = feed.grab_multi()
    win = grab(h)
    win.save(os.path.join(OUT, "window_vp%d.png" % vi))
    gl = gl_crop(win)
    gl.save(os.path.join(OUT, "gl_vp%d.png" % vi))
    print("== 视口 index %d  gl=%s ==" % (vi, gl.size))
    g = cv(gl)
    for name in ("head", "left", "right"):
        v = fr.get(name)
        if v is None:
            continue
        Image.fromarray(v).save(os.path.join(OUT, "vp%d_stream_%s.png" % (vi, name)))
        print("   vs stream_%-5s %s  NCC=%.3f" % (name, "%dx%d" % (v.shape[1], v.shape[0]), ncc(g, cv(Image.fromarray(v)))))
    ap = os.path.expanduser("~/.orcalab/viewport_image/color/AgentCamera_color_0.png")
    if os.path.exists(ap):
        try:
            shutil.copy(ap, os.path.join(OUT, "vp%d_agent.png" % vi))
            print("   vs agent      %s  NCC=%.3f" % (Image.open(ap).size, ncc(g, cv(Image.open(ap)))))
        except Exception as e:
            print("   agent err", e)

feed.close()
env.close()
print("DONE")
