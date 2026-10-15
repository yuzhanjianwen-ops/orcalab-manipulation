# -*- coding: utf-8 -*-
import os, sys, io, json, math
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
for a in ["/Group/Static_Objcets/Table", "/dual_arm_collaborative_service_robot_1",
          "/calcium_gluconate_tablets_bottle_1", "/qiangli_pipalu_medication_box_1"]:
    try:
        r = call_text(m, "get_actor_asset_aabb", {"actor_path": a})
        print("AABB", a, "->", r[:260])
    except Exception as e:
        print("AABB", a, "err", str(e)[:100])
# head cam world transform via viewport (idx1 = head)
for i in (1,):
    call_text(m, "set_viewport_camera", {"camera_index": i})