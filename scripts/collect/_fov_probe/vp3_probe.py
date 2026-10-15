# -*- coding: utf-8 -*-
import os, sys, io, json, time, shutil
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
from PIL import Image
OUT = os.path.join(HERE, "_fov_probe", "vp3")
os.makedirs(OUT, exist_ok=True)
m = OrcaMcp(); m.connect()
print("state:", call_text(m, "get_simulation_state", {}))
print("cur viewport info:", call_text(m, "get_viewport_camera_info", {})[:400])
ts = {t["name"]: t for t in m.tools()}
print("get_viewport_png schema:", json.dumps(ts["get_viewport_png"].get("inputSchema", {})))
# render each index WITHOUT switching the displayed camera
for i in range(6):
    try:
        r = call_text(m, "get_viewport_png", {"index": i})
    except Exception as e:
        print(i, "ERR", e); continue
    print("idx", i, "->", r[:200])