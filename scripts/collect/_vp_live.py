# -*- coding: utf-8 -*-
"""列出 OrcaLab MCP 工具 + 当前 6 个视口相机的位姿/scale + 机载相机注册表。"""
import os, sys, io, json, time
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text

m = OrcaMcp()
print("serverInfo:", m.connect())
ts = [t["name"] for t in m.tools()]
print("MCP 工具 (%d):" % len(ts))
print("  " + ", ".join(ts))
print()
vp_tools = [n for n in ts if "view" in n.lower() or "camera" in n.lower()]
print("与视口/相机相关的工具:", vp_tools)
print()
print("=== 当前视口相机 ===")
try:
    print(call_text(m, "get_viewport_camera_info", {})[:500])
except Exception as e:
    print("err", e)
print()
print("=== 逐个切 0..5 读位姿 ===")
for i in range(6):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": i})
        time.sleep(0.25)
        r = json.loads(call_text(m, "get_viewport_transform", {}))
        t = r.get("transform", r)
        pos = [round(x, 3) for x in t.get("position", [])]
        scale = t.get("scale", -1)
        kind = "机载镜头" if abs(scale - 1.695) < 0.01 else ("自由相机" if abs(scale - 1.0) < 0.01 else "?")
        print("  idx %d  scale=%.3f  %-10s pos=%s" % (i, scale, kind, pos))
    except Exception as e:
        print("  idx %d err %s" % (i, str(e)[:80]))
