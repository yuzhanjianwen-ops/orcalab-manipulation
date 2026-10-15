# -*- coding: utf-8 -*-
import sys, io, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text

m = OrcaMcp()
m.connect()
d = json.loads(call_text(m, "get_entity_hierarchy",
                         {"asset_path": "/dual_arm_collaborative_service_robot_1"}))

hits = []


def walk(n):
    nm = n.get("name", "")
    p = n.get("entity_path", "")
    if "camera" in nm.lower():
        hits.append((p, nm))
    for c in n.get("children", []) or []:
        walk(c)


walk(d)
print("=== 机器人资产里的相机节点（含完整父链）===")
for p, nm in hits:
    print("  %-40s" % nm)
    print("     %s" % p)

print("\n=== 关键挂点链接检查 ===")
for key in ("head_link2", "arm_l_end_link", "arm_r_end_link", "camera_head", "camera_left", "camera_right"):
    found = [p for p, nm in hits if key in nm] if "camera" in key else []
    print("  %-16s in-camera-nodes=%s" % (key, bool(found)))
