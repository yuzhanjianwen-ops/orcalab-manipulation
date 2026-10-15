# -*- coding: utf-8 -*-
import os, sys, io, json
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
ts = {t["name"]: t for t in m.tools()}
for n in ["get_actor_properties", "get_actor_transform", "get_entity_hierarchy"]:
    print("="*20, n)
    print(json.dumps(ts[n].get("inputSchema", {}), ensure_ascii=False)[:600])
P = "/dual_arm_collaborative_service_robot_1"
for ent in ["camera_head", "camera_left", "camera_right"]:
    p = "%s/%s_body2/cameras/%s" % (P, ent, ent)
    r = call_text(m, "get_actor_properties", {"asset_path": p})
    print("="*20, p); print(r[:1400])