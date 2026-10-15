# -*- coding: utf-8 -*-
"""对比各场景 JSON 的 package_references 与引擎当前 asset_sync_state 的包 id。

用法：
    python _pkg_check.py                # 巡检 scenes/ 目录下的场景文件
    python _pkg_check.py <场景目录>      # 指定其他目录

asset_sync_state.json 会自动定位（每台机器的工程 GUID 不同，不能写死）；
也可用环境变量 ORCA_ASSET_SYNC_STATE 显式指定。
"""
import json, io, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = sys.argv[1] if len(sys.argv) > 1 else HERE


def _find_state():
    """自动定位 asset_sync_state.json。"""
    cands = []
    env = os.environ.get("ORCA_ASSET_SYNC_STATE")
    if env:
        cands.append(env)

    roots = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        roots.append(os.path.join(la, "Orca", "OrcaStudio"))
    roots.append(os.path.join(os.path.expanduser("~"), "AppData", "Local",
                              "Orca", "OrcaStudio"))
    for root in roots:
        if not os.path.isdir(root):
            continue
        for guid in sorted(os.listdir(root)):
            p = os.path.join(root, guid, "user", "asset_sync_state.json")
            if os.path.exists(p) and p not in cands:
                cands.append(p)
    for p in cands:
        if os.path.exists(p):
            return p
    raise SystemExit(
        "找不到 asset_sync_state.json。\n"
        "  预期位置：%%LOCALAPPDATA%%\\Orca\\OrcaStudio\\<工程GUID>\\user\\asset_sync_state.json\n"
        "  请确认 OrcaStudio 已启动过并同步过资产；\n"
        "  或用环境变量 ORCA_ASSET_SYNC_STATE 指定完整路径。\n"
        "  已尝试：%s" % cands
    )


STATE = _find_state()

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
