# -*- coding: utf-8 -*-
import os, sys, io, json
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
P = "/dual_arm_collaborative_service_robot_1"
for p in [P, P + "/camera_head", P + "/camera_left", P + "/camera_right",
          P + "/camera_right_body2", P + "/camera_left_body2", P + "/camera_head_body2"]:
    r = call_text(m, "get_actor_transform", {"actor_path": p})
    print("---", p)
    print("   ", r[:260])