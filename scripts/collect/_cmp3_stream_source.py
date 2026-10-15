# -*- coding: utf-8 -*-
"""判定 7070/7080/7090 推流到底来自哪台相机 —— 可逆。

背景：引擎相机注册表里有 6 台相机：
    机载   camera_head / camera_left / camera_right      (streaming=True)
    静置   camera / camera_<hash> / camera_<hash>        (由 /head_camera_1,
                                                          /wrist_camera_l,
                                                          /wrist_camera_r
                                                          三个场景 Actor 提供)
且启动仿真时日志出现 "Port 7070 already in use, allocated new port 7091"。
两组相机抢同一批端口，所以必须实测哪一组在推流。

方法：仿真跑起来后先抓一帧推流 -> A；把三台静置相机搬到高空 -> 再抓 -> B；
      还原。A≈B 说明推流与静置相机无关（= 机载相机），A≠B 说明推流其实来自静置相机。

产出： _fov_probe/camsrc/
"""
import os
import sys
import io
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "teleop")))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
import cv2

import orca_boot  # noqa: F401
from orca_rig import OrcaRig
from ws_camera import WsCameraFeed
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "camsrc")
os.makedirs(OUT, exist_ok=True)

STATIC = ("/head_camera_1", "/wrist_camera_l", "/wrist_camera_r")
MOVED = {
    "/head_camera_1": ([18.0, -3.0, 19.0], [-85.0, 0.0, 0.0]),
    "/wrist_camera_l": ([13.0, -9.0, 19.0], [-85.0, 0.0, 0.0]),
    "/wrist_camera_r": ([23.0, 3.0, 19.0], [-85.0, 0.0, 0.0]),
}

log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


m = OrcaMcp()
m.connect()
say("sim:", call_text(m, "get_simulation_state", {})[:90])

rig = OrcaRig()
rig.lock_base(0.0)
q0 = {s: np.asarray(rig.arm_qpos(s), dtype=float).copy() for s in ("l", "r")}
ctrl = rig.ctrl(q0)
say("左臂关节:", np.round(q0["l"], 3).tolist())

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
say("feed.open ->", ok, "|", feed.error)


def pump(sec=1.5):
    t = time.time() + sec
    while time.time() < t:
        drive()
        for s in feed._streams:
            s._tick()
        time.sleep(1 / 30)


def shot(tag):
    pump(1.2)
    fr = feed.grab_multi() or {}
    for k, v in fr.items():
        if v is not None:
            cv2.imwrite(os.path.join(OUT, "%s_%s.png" % (tag, k)),
                        cv2.cvtColor(v, cv2.COLOR_RGB2BGR))
    say(tag, ":", {k: (None if v is None else v.shape) for k, v in fr.items()})
    return {k: v for k, v in fr.items() if v is not None}


d = json.loads(call_text(m, "get_all_actors", {}))
orig = {}
for a in STATIC:
    v = d.get(a) or {}
    orig[a] = (v.get("transform.position"), v.get("transform.rotation"))
    say("原始 %-18s pos=%s" % (a, orig[a][0]))

A = shot("A_before")
say("--- 搬走三台静置相机 ---")
for a, (p, r) in MOVED.items():
    call_text(m, "set_actor_transform", {"actor_path": a, "position": p, "rotation": r})
    say("   moved", a, "->", p)
time.sleep(0.8)
B = shot("B_moved")

say("--- 还原 ---")
for a, (p, r) in orig.items():
    call_text(m, "set_actor_transform", {"actor_path": a, "position": p, "rotation": r})

res = {}
for k in A:
    if k not in B:
        continue
    a = A[k].astype(np.float32)
    b = B[k].astype(np.float32)
    diff = float(np.abs(a - b).mean())
    res[k] = diff
    say("推流 %-6s 搬运前后 平均像素差 = %.2f  -> %s" % (
        k, diff, "随静置相机变化（推流=静置相机！）" if diff > 3 else
        "不受静置相机影响（推流=机载相机）"))
feed.close()
with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE")
