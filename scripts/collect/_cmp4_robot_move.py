# -*- coding: utf-8 -*-
"""判定推流相机是否真的挂在机器人上：把机器人整体抬高 3m，看 7070/7080/7090 变不变。

变  -> 推流相机确实跟机器人走（extrinsics 生效），画面空旷另有原因；
不变 -> 推流根本不是机器人视角（渲染用了错的位姿/空场景）。

同时测：把 Table 抬高 3m，看推流是否出现桌子（判断物理层里有没有桌子）。

产出： _fov_probe/robotmove/
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

OUT = os.path.join(HERE, "_fov_probe", "robotmove")
os.makedirs(OUT, exist_ok=True)

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
say("基座 qpos:", np.round(rig.d.qpos[rig.BQ:rig.BQ + 7], 4).tolist())
base_z0 = float(rig.base0[2])

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


def pump(sec=1.5):
    t = time.time() + sec
    while time.time() < t:
        drive()
        for s in feed._streams:
            s._tick()
        time.sleep(1 / 30)


def shot(tag):
    pump(1.5)
    fr = feed.grab_multi() or {}
    for k, v in fr.items():
        if v is not None:
            cv2.imwrite(os.path.join(OUT, "%s_%s.png" % (tag, k)),
                        cv2.cvtColor(v, cv2.COLOR_RGB2BGR))
    say(tag, ":", {k: (None if v is None else v.shape) for k, v in fr.items()})
    return {k: v for k, v in fr.items() if v is not None}


def diff(A, B, title):
    for k in A:
        if k in B:
            d = float(np.abs(A[k].astype(np.float32) - B[k].astype(np.float32)).mean())
            say("  %-24s %-6s 像素差 %.2f -> %s" % (
                title, k, d, "变了" if d > 3 else "没变"))


A = shot("A_base")
say("--- 机器人抬高 3m（改 base0 的 z）---")
rig.base0 = rig.base0.copy()
rig.base0[2] = base_z0 + 3.0
B = shot("B_up3")
diff(A, B, "抬机器人3m")

say("--- 还原机器人 ---")
rig.base0[2] = base_z0
shot("C_back")

say("--- 抬高 Table ---")
d = json.loads(call_text(m, "get_all_actors", {}))
tp = None
for k, v in d.items():
    if k.endswith("/Table") or v.get("name") == "Table":
        tp = list(v.get("transform.position") or [])
        say("  Table 原位置", tp)
        break
D = None
if tp:
    call_text(m, "set_actor_transform",
              {"actor_path": "/Group/Static_Objcets/Table",
               "position": [tp[0], tp[1], tp[2] + 3.0], "rotation": [0, 0, 90]})
    D = shot("D_table_up")
    call_text(m, "set_actor_transform",
              {"actor_path": "/Group/Static_Objcets/Table",
               "position": tp, "rotation": [0, 0, 90]})
    if D:
        diff(A, D, "抬桌子3m")

feed.close()
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE")
