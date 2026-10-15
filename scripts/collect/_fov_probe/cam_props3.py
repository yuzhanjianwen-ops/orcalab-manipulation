# -*- coding: utf-8 -*-
import os, sys, io, json
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
P = "/dual_arm_collaborative_service_robot_1"
for ent in ["camera_head", "camera_left", "camera_right"]:
    for p in [P + "/" + ent]:
        r = call_text(m, "get_actor_properties", {"asset_path": p})
        print("="*25, p); print(r[:1600])
h = call_text(m, "get_entity_hierarchy", {"asset_path": P})
print("="*25, "hierarchy (truncated)"); print(h[:2500])