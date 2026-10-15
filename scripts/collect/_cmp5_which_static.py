# -*- coding: utf-8 -*-
"""逐一搬走三台场景静置相机，定位到底哪一台占用了 7070 端口（head 推流）。

产出： _fov_probe/camsrc2/
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

OUT = os.path.join(HERE, "_fov_probe", "camsrc2")
os.makedirs(OUT, exist_ok=True)
STATIC = ("/head_camera_1", "/wrist_camera_l", "/wrist_camera_r")
log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


m = OrcaMcp()
m.connect()
rig = OrcaRig()
rig.lock_base(0.0)
q0 = {s: np.asarray(rig.arm_qpos(s), dtype=float).copy() for s in ("l", "r")}
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
say("open:", feed.open(driver=drive), "|", feed.error)


def pump(sec=1.4):
    t = time.time() + sec
    while time.time() < t:
        drive()
        for s in feed._streams:
            s._tick()
        time.sleep(1 / 30)


def shot(tag):
    pump()
    fr = feed.grab_multi() or {}
    for k, v in fr.items():
        if v is not None:
            cv2.imwrite(os.path.join(OUT, "%s_%s.png" % (tag, k)),
                        cv2.cvtColor(v, cv2.COLOR_RGB2BGR))
    return {k: v for k, v in fr.items() if v is not None}


d = json.loads(call_text(m, "get_all_actors", {}))
orig = {a: (d[a]["transform.position"], d[a]["transform.rotation"]) for a in STATIC}
say("原始位姿:", {k: [round(x, 3) for x in v[0]] for k, v in orig.items()})

BASE = shot("base")
report = {}
for cam in STATIC:
    p, r = orig[cam]
    far = [p[0] + 6.0, p[1] + 6.0, 25.0]
    call_text(m, "set_actor_transform", {"actor_path": cam, "position": far,
                                        "rotation": [-89.0, 0.0, 0.0]})
    time.sleep(0.6)
    M = shot("only_" + cam.strip("/"))
    call_text(m, "set_actor_transform", {"actor_path": cam, "position": p, "rotation": r})
    time.sleep(0.5)
    row = {}
    for k in BASE:
        if k in M:
            row[k] = round(float(np.abs(BASE[k].astype(np.float32)
                                       - M[k].astype(np.float32)).mean()), 2)
    report[cam] = row
    say("只搬走 %-18s -> 各推流像素差 %s" % (cam, row))

feed.close()
with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE")
