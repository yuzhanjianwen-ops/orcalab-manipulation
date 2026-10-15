# -*- coding: utf-8 -*-
"""对比各场景 JSON 的 package_references 与引擎当前 asset_sync_state 的包 id。"""
import json, io, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCENE_DIR = r"D:\OTHERS\OrcaLab\SimpleMovement"
STATE = r"C:\Users\86322\AppData\Local\Orca\OrcaStudio\{3DB8A56E-2458-4543-93A1-1A41756B97DA}\user\asset_sync_state.json"

state = json.load(io.open(STATE, encoding="utf-8"))
by_id, by_name, by_file = {}, {}, {}
for p in state["logical_packages"]:
    bp = p.get("base_package") or {}
    by_id[p["id"]] = p
    by_name[p["name"]] = p
    if bp.get("file_name"):
        by_file[bp["file_name"].replace(".pak", "")] = p

print("=== 引擎当前注册的逻辑包 ===")
for p in state["logical_packages"]:
    bp = p.get("base_package") or {}
    print("  %-38s %-26s file=%s" % (p["id"], p["name"], bp.get("file_name")))

scenes = [f for f in sorted(os.listdir(SCENE_DIR)) if f.endswith(".json") and "_pkg" not in f]
print()
for fn in scenes:
    path = os.path.join(SCENE_DIR, fn)
    try:
        d = json.load(io.open(path, encoding="utf-8"))
    except Exception as e:
        print("== %s  解析失败: %s" % (fn, e)); continue
    pr = d.get("package_references") or []
    print("== %s  (%d 个引用) ==" % (fn, len(pr)))
    for r in pr:
        rid, rname = r.get("id"), r.get("name")
        tag = "OK"
        cur = by_id.get(rid)
        if cur is None:
            if rid in by_file:
                cur = by_file[rid]
                tag = "ID变了! -> 新id %s" % cur["id"]
            elif rname in by_name:
                cur = by_name[rname]
                tag = "ID变了! -> 新id %s" % cur["id"]
            else:
                tag = "缺失(引擎里没有)"
        print("   %-38s %-26s %s" % (rid, rname, tag))
