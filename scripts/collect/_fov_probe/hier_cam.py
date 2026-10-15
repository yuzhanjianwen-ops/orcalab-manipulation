# -*- coding: utf-8 -*-
import os, sys, io, json, re
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
h = call_text(m, "get_entity_hierarchy", {"asset_path": "/dual_arm_collaborative_service_robot_1"})
d = json.loads(h)
# walk, print any node whose path mentions camera
def walk(n):
    p = n.get("entity_path", "")
    if "camera" in p.lower():
        print(p, "  <-- children:", [c.get("name") for c in n.get("children", [])])
    for c in n.get("children", []):
        walk(c)
walk(d)