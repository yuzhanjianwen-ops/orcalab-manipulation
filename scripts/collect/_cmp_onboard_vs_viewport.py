# -*- coding: utf-8 -*-
"""同帧对比：机器人机载推流(7070/7080/7090) vs OrcaStudio 视口逐相机渲染。

为什么跑这个
============
编辑服务(50151) 列出的视口相机是 7 台：
    idx0  Camera          (level)                自由相机
    idx1  camera_head     /dual_arm_...robot_1   机载
    idx2  camera_left     /dual_arm_...robot_1   机载
    idx3  camera_right    /dual_arm_...robot_1   机载
    idx4  camera          /head_camera_1         场景静置相机
    idx5  camera          /wrist_camera_l        场景静置相机
    idx6  camera          /wrist_camera_r        场景静置相机
7 台全渲染一遍（编辑器窗口裁出的 3D 区 = 用户真正看到的东西），
同时抓三路推流，回答"推流是不是同一台相机、构图差在哪"。

驱动仿真走项目里已验证可用的 OrcaRig（collect.py 同款），
裸 OrcaGymLocalEnv + do_simulation 推不出帧。

产出： _fov_probe/onboard/
    view_idxN.png    视口切到 index=N 时编辑器 3D 区
    stream_<tag>.png 机载推流（head/left/right）
    poses.json       每个 index 的视口相机世界位姿
    report.txt
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

OUT = os.path.join(HERE, "_fov_probe", "onboard")
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
        if n.value.strip().startswith("26.8.1"):
            hw.append(h)
        return True

    u.EnumWindows(CB(cb), None)
    return hw[0] if hw else None


def grab(h):
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.6)
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
say("MCP ok | sim:", call_text(m, "get_simulation_state", {})[:80])
hw = find_orca()
say("OrcaStudio hwnd:", hw)

rig = OrcaRig()
say("OrcaRig 已连接: nu=%d dt=%.4f" % (rig.m.nu, rig.dt))
ctrl = rig.ctrl()                      # 保持当前姿态
sim = [0]


def drive():
    sim[0] += 1
    rig._hold()
    rig.u.set_ctrl(ctrl)
    rig.u.do_simulation(ctrl, rig.u.frame_skip)
    rig._hold()
    rig.u.render(simulate_index=sim[0], request_idr=(sim[0] == 0))


feed = WsCameraFeed()
try:
    ok = feed.open(driver=drive)
    say("WsCameraFeed.open ->", ok, "|", feed.error)
    t = time.time()
    while time.time() - t < 4.0:
        drive()
        for s in feed._streams:
            s._tick()
        time.sleep(1 / 30)
    fr = feed.grab_multi() or {}
    say("推流帧:", {k: (None if v is None else v.shape) for k, v in fr.items()})
    for tag, v in fr.items():
        if v is None:
            continue
        cv2.imwrite(os.path.join(OUT, "stream_%s.png" % tag),
                    cv2.cvtColor(v, cv2.COLOR_RGB2BGR))
except Exception as e:
    say("推流段异常:", type(e).__name__, str(e)[:200])

# ---------------------------------------------------------------- 逐视口渲染
poses = {}
for idx in range(7):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": idx})
    except Exception as e:
        say("idx%d set err %s" % (idx, str(e)[:80]))
    time.sleep(1.0)
    try:
        for _ in range(10):
            drive()
            time.sleep(1 / 30)
    except Exception:
        pass
    try:
        t = json.loads(call_text(m, "get_viewport_transform", {}))
        poses[idx] = t.get("transform", t)
    except Exception:
        poses[idx] = {}
    if hw:
        try:
            im = grab(hw)
            cr = gl_crop(im)
            cr.save(os.path.join(OUT, "view_idx%d.png" % idx))
            say("idx%d  gl=%s  pos=%s scale=%s" % (
                idx, "%dx%d" % cr.size,
                [round(x, 3) for x in poses[idx].get("position", [])],
                poses[idx].get("scale")))
        except Exception as e:
            say("idx%d grab err %s" % (idx, e))

with open(os.path.join(OUT, "poses.json"), "w", encoding="utf-8") as f:
    json.dump({str(k): v for k, v in poses.items()}, f, ensure_ascii=False, indent=2)

try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass
try:
    feed.close()
except Exception:
    pass

with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE", OUT)
