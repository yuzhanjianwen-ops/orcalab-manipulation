# -*- coding: utf-8 -*-
"""干净版同帧对比：锁基座 + 保持布局初始姿态，再抓 机载推流 vs 视口。

上一版(_cmp_onboard_vs_viewport.py)没锁基座，机器人几秒内就倒地，
导致推流里什么都没有 —— 不能用来判断构图差异。

产出： _fov_probe/onboard2/
"""
import os
import sys
import io
import time
import json
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "teleop")))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
import cv2
from PIL import Image, ImageGrab

import orca_boot  # noqa: F401
from orca_rig import OrcaRig
from ws_camera import WsCameraFeed
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "onboard2")
os.makedirs(OUT, exist_ok=True)

u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))


def find_orca():
    hw = []

    def cb(h, l):
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
    time.sleep(0.55)
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


log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


m = OrcaMcp()
m.connect()
say("sim:", call_text(m, "get_simulation_state", {})[:80])
hw = find_orca()
say("hwnd:", hw)

rig = OrcaRig()
rig.lock_base(0.0)                       # 立刻钉住浮动基座
q0 = {s: np.asarray(rig.arm_qpos(s), dtype=float).copy() for s in ("l", "r")}
say("初始左臂关节:", np.round(q0["l"], 4).tolist())
say("初始右臂关节:", np.round(q0["r"], 4).tolist())
say("基座 qpos:", np.round(rig.d.qpos[rig.BQ:rig.BQ + 7], 4).tolist())
ctrl = rig.ctrl(q0)

sim = [0]


def drive():
    sim[0] += 1
    rig._hold()
    rig.u.set_ctrl(ctrl)
    rig.u.do_simulation(ctrl, rig.u.frame_skip)
    rig._hold()
    rig.u.render(simulate_index=sim[0], request_idr=(sim[0] == 0))


feed = WsCameraFeed()
ok = feed.open(driver=drive)
say("WsCameraFeed.open ->", ok, "|", feed.error)
t = time.time()
while time.time() - t < 2.0:
    drive()
    for s in feed._streams:
        s._tick()
    time.sleep(1 / 30)

say("抓推流 …")
fr = feed.grab_multi() or {}
say("推流帧:", {k: (None if v is None else v.shape) for k, v in fr.items()})
for tag, v in fr.items():
    if v is not None:
        cv2.imwrite(os.path.join(OUT, "stream_%s.png" % tag),
                    cv2.cvtColor(v, cv2.COLOR_RGB2BGR))

# 紧接着同一姿态抓视口（先 head/left/right 三台）
say("抓视口 idx1..3 …")
for idx in (1, 2, 3):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": idx})
    except Exception as e:
        say("  idx%d set err %s" % (idx, str(e)[:70]))
    for _ in range(6):
        drive()
    time.sleep(0.8)
    try:
        t2 = json.loads(call_text(m, "get_viewport_transform", {}))
        tr = t2.get("transform", t2)
    except Exception:
        tr = {}
    if hw:
        im = gl_crop(grab(hw))
        im.save(os.path.join(OUT, "view_idx%d.png" % idx))
        say("  idx%d %s pos=%s scale=%s" % (idx, "%dx%d" % im.size,
            [round(x, 3) for x in tr.get("position", [])], tr.get("scale")))

# 同一姿态再抓一次推流，作为"紧邻视口那一帧"
fr2 = feed.grab_multi() or {}
for tag, v in fr2.items():
    if v is not None:
        cv2.imwrite(os.path.join(OUT, "stream2_%s.png" % tag),
                    cv2.cvtColor(v, cv2.COLOR_RGB2BGR))
say("第二次推流:", {k: (None if v is None else v.shape) for k, v in fr2.items()})

try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass
feed.close()

with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE", OUT)
