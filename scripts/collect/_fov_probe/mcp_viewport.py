# -*- coding: utf-8 -*-
import os, sys, io, json
sys.path.insert(0, r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp(); m.connect()
OUT = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe"
for name in ["get_simulation_state", "get_engine_info", "get_viewport_camera_info", "get_viewport_transform"]:
    try:
        t = call_text(m, name, {}, timeout=30)
        print("="*30, name); print(t[:1500])
    except Exception as e:
        print(name, "ERR", type(e).__name__, e)