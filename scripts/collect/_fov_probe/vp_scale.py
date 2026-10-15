# -*- coding: utf-8 -*-
import os, sys, io, json, time
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
for idx in range(6):
    call_text(m, "set_viewport_camera", {"camera_index": idx})
    time.sleep(0.3)
    r = call_text(m, "get_viewport_transform", {})
    try:
        t = json.loads(r)["transform"]
        pos = [round(x, 3) for x in t["position"]]
        print("idx %d scale=%.3f pos=%s rot=%s" % (idx, t.get("scale", -1), pos, [round(x,1) for x in t["rotation"]]))
    except Exception as e:
        print("idx", idx, r[:200])
# also robot arm end link world transforms via MCP
P = "/dual_arm_collaborative_service_robot_1"
for p in [P + "/mujoco_wrap/rootPrim/robot_holder1/robot_holder1/body_link1/body_link2:2/head_link1:5/head_link2/camera_head_body1:2/camera_head_body2:1",
          P + "/mujoco_wrap/rootPrim/robot_holder1/robot_holder1/body_link1/body_link2:2/arm_r_link1:1/arm_r_link2:1/arm_r_link3:2/arm_r_link4:2/arm_r_link5/arm_r_link6/arm_r_end_link:1/camera_right_body1:2/camera_right_body2"]:
    try: print("T", p.split("/")[-1], call_text(m, "get_actor_transform", {"actor_path": p})[:300])
    except Exception as e: print("T err", e)