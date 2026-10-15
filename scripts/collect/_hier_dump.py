# -*- coding: utf-8 -*-
import sys, io, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text

m = OrcaMcp()
m.connect()
raw = call_text(m, "get_entity_hierarchy", {"asset_path": " /dual_arm_collaborative_service_robot_1"})
print("len(raw) =", len(raw))
print(raw[:1200])
print("....")
try:
    d = json.loads(raw)
    print("top-level type:", type(d).__name__)
    if isinstance(d, dict):
        print("keys:", list(d.keys())[:20])
except Exception as e:
    print("json err", e)
