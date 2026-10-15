# -*- coding: utf-8 -*-
"""验证假设：camera_head 的偏移差 ≈ (1.6954-1)*|相机本地偏移|  —— 即父节点 scale 没乘进相机偏移。

要拿到的东西：
  * 引擎场景全部 actor（路径 / 位姿 / scale / parent）
  * 机器人的 actor 属性（看有没有 scale=1.6954）
  * 各相机的 actor 属性

产出： _fov_probe/actors2/report.txt
"""
import os
import sys
import io
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "actors2")
os.makedirs(OUT, exist_ok=True)
log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


m = OrcaMcp()
m.connect()
say("sim:", call_text(m, "get_simulation_state", {})[:70])
say("")
say("=" * 78)
say("全部 actor")
say("=" * 78)
raw = call_text(m, "get_all_actors", {}, timeout=60)
try:
    d = json.loads(raw)
except Exception:
    say("解析失败:", raw[:300])
    d = {}
say("总数:", len(d), "  (顶层键示例:", list(d.keys())[:6], ")")
for k, v in sorted(d.items()):
    pos = v.get("transform.position") or v.get("world_transform.position")
    rot = v.get("transform.rotation") or v.get("world_transform.rotation")
    sc = v.get("transform.scale") or v.get("world_transform.scale")
    par = v.get("parent") or v.get("parent_path") or v.get("parent_name")
    say("  %-46s" % k)
    say("        pos=%s" % ([round(float(x), 4) for x in pos] if pos else None))
    say("        rot=%s  scale=%s  parent=%s" % (
        [round(float(x), 3) for x in rot] if rot else None, sc, par))

say("")
say("=" * 78)
say("机器人 / 相机 的属性明细")
say("=" * 78)
for ap in ("/dual_arm_collaborative_service_robot_1",
           "/head_camera_1", "/wrist_camera_l", "/wrist_camera_r"):
    try:
        t = call_text(m, "get_actor_properties", {"actor_path": ap}, timeout=30)
        say("--- %s ---" % ap)
        say(t[:1500])
    except Exception as e:
        say("--- %s 失败: %s %s" % (ap, type(e).__name__, e))

say("")
say("=" * 78)
say("实体层级 get_entity_hierarchy")
say("=" * 78)
for ap in ("", "/dual_arm_collaborative_service_robot_1"):
    try:
        t = call_text(m, "get_entity_hierarchy",
                      {"actor_path": ap} if ap else {}, timeout=40)
        say("--- root=%r ---" % ap)
        say(t[:2500])
    except Exception as e:
        say("--- root=%r 失败: %s %s" % (ap, type(e).__name__, e))

with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("\nDONE", OUT)
