# -*- coding: utf-8 -*-
import os, sys, io, json
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
ts = {t["name"]: t for t in m.tools()}
for n in ["get_view_png_from_transform", "get_viewport_png", "set_viewport_camera", "get_actor_transform"]:
    print("="*18, n)
    print(json.dumps(ts[n].get("inputSchema", {}), ensure_ascii=False))
r = call_text(m, "get_actor_transform", {"actor_path": "/dual_arm_collaborative_service_robot_1"})
print("robot actor transform:", r[:400])