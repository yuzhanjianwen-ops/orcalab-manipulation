# -*- coding: utf-8 -*-
"""核验：采集用的 camera_head/left/right 到底挂在哪 —— 机器人身上？还是悬浮 Actor？"""
import sys, io, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text

m = OrcaMcp()
m.connect()

print("=== 引擎里注册的相机（= 采集能用的相机）===")
import socket
print("(端口) 7070/7080/7090 ->", end=" ")
for p in (7070, 7080, 7090):
    s = socket.socket(); s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", p)); print("%d OPEN" % p, end="  ")
    except Exception:
        print("%d closed" % p, end="  ")
    finally:
        s.close()
print()

print("\n=== 场景里所有含 camera 的 Actor（含完整层级路径）===")
h = call_text(m, "get_entity_hierarchy", {"asset_path": " "})
try:
    d = json.loads(h)
except Exception:
    d = None

if d is None:
    # 退路：直接列 actors
    a = json.loads(call_text(m, "get_all_actors", {}))
    for k, v in a.items():
        if "camera" in k.lower():
            print("  ", k, v.get("type"), v.get("transform", {}).get("position"))
else:
    rows = []

    def walk(n, depth):
        p = n.get("entity_path") or n.get("name") or ""
        if "camera" in p.lower():
            rows.append((len(p.split("/")), p))
        for c in n.get("children", []) or []:
            walk(c, depth + 1)

    # 可能是 list 或多个 root
    if isinstance(d, list):
        for it in d:
            walk(it, 0)
    else:
        walk(d, 0)
    for dep, p in sorted(rows):
        print("  depth=%d  %s" % (dep, p))

print("\n=== 顶层 actor 一览（depth<=2 的），看有无悬浮相机 ===")
a = json.loads(call_text(m, "get_all_actors", {}))
for k, v in a.items():
    if k.count("/") <= 2:
        print("  %-70s %s" % (k[:70], v.get("type")))
