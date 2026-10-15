# -*- coding: utf-8 -*-
u"""核验：数据采集用的相机，是不是【机器人自带】的？

用法：
    python check_camera_source.py

它做四件事：
  1) 列出场景里顶层的相机 Actor —— 有的话就是「悬浮相机」；
  2) 把 camera_head / camera_left / camera_right 的完整父链打出来，
     看它们挂在机器人的哪根 link 上；
  3) 探测推流端口 7070/7080/7090；
  4) 告诉你在 collect.py 里应该用哪个开关。

只读，不改场景。
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from orca_mcp import OrcaMcp, call_text  # noqa: E402

TARGETS = ("camera_head", "camera_left", "camera_right")
PORTS = (7070, 7080, 7090)
ROBOT_HINT = "dual_arm_collaborative_service_robot"


def main() -> int:
    try:
        m = OrcaMcp()
        m.connect()
    except Exception as e:                                  # noqa: BLE001
        print("[x] 连不上 OrcaStudio MCP(12345)：%s: %s" % (type(e).__name__, e))
        print("    确认 OrcaStudio 已打开场景并处于运行状态。")
        return 1

    # ---------- 1) 顶层 actor，找悬浮相机 ----------
    print("=" * 70)
    print("1) 场景顶层 Actor（顶层出现 camera 节点 = 悬浮相机）")
    print("=" * 70)
    actors = json.loads(call_text(m, "get_all_actors", {}))
    floating = []
    for k, v in sorted(actors.items()):
        depth = k.count("/")
        if depth <= 2:
            tag = ""
            if "camera" in k.lower():
                tag = "   <== 悬浮相机！"
                floating.append(k)
            print("   %-58s %s%s" % (k[:58], v.get("type"), tag))
    if floating:
        print("\n   [警告] 顶层存在相机 Actor：%s" % ", ".join(floating))
        print("          这些不是机器人相机，采集时不要用。")
    else:
        print("\n   [OK] 顶层没有相机 Actor —— 场景里没有悬浮相机。")

    # ---------- 2) 相机挂点 ----------
    print()
    print("=" * 70)
    print("2) 三相机挂在机器人的哪根 link 上")
    print("=" * 70)
    robot_key = None
    for k in actors:
        if ROBOT_HINT in k:
            robot_key = k
            break
    if robot_key is None:
        print("   [x] 没找到机器人 Actor")
    else:
        hier = json.loads(call_text(m, "get_entity_hierarchy", {"asset_path": robot_key}))
        found = {}

        def walk(n):
            nm = n.get("name", "")
            if nm in TARGETS:
                found[nm] = n.get("entity_path", "")
            for c in n.get("children", []) or []:
                walk(c)

        walk(hier)
        for cam in TARGETS:
            path = found.get(cam)
            if not path:
                print("   %-14s [x] 没找到" % cam)
                continue
            parent = path.split("/")[-2] if "/" in path else "?"
            print("   %-14s -> 挂在: %s" % (cam, parent))
            print("      完整路径: %s" % path.replace("/<root>", ""))
        if found:
            print("\n   [OK] 三台相机都在机器人资产内部（%s）。" % robot_key)

    # ---------- 3) 端口 ----------
    print()
    print("=" * 70)
    print("3) 推流端口")
    print("=" * 70)
    for p in PORTS:
        s = socket.socket()
        s.settimeout(0.6)
        try:
            s.connect(("127.0.0.1", p))
            print("   %d  LISTENING  (推流已开)" % p)
        except Exception:
            print("   %d  closed     (没开推流；采集时 env.start_streaming 会打开)" % p)
        finally:
            s.close()

    # ---------- 4) 结论 ----------
    print()
    print("=" * 70)
    print("4) 采集该怎么启动")
    print("=" * 70)
    print("   机器人自带三相机（推荐）:")
    print("       collect.py --keyboard --cam3-ws --lerobot-out <DIR> --task \"...\"")
    print("   机器人自带三相机（视口渲染，慢）:")
    print("       collect.py --keyboard --cam3 ...")
    print("   ★ 现在 --cam3-ws 也是默认：不加任何相机开关就走机载三相机。")
    print("   --camera 走的是 Studio 悬浮相机 AgentCamera，默认已被拒绝。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
