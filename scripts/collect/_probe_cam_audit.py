# -*- coding: utf-8 -*-
"""对比：编辑器(50151)相机表  vs  引擎(MCP)场景里相机实体的真实位姿。

目的：解释「视口 idx1(camera_head) 能看到桌面，引擎同姿态渲染却是全黑（相机被头部外壳包住）」。

产出： _fov_probe/camauadit/report.txt
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

OUT = os.path.join(HERE, "_fov_probe", "camauadit")
os.makedirs(OUT, exist_ok=True)
log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


say("=" * 70)
say("A. 编辑器 50151 GetCameras()")
say("=" * 70)
try:
    import grpc
    import orcalab.protos.edit_service_pb2 as ep
    import orcalab.protos.edit_service_pb2_grpc as epg
    stub = epg.GrpcServiceStub(grpc.insecure_channel("127.0.0.1:50151"))
    r = stub.GetCameras(ep.GetCamerasRequest(), timeout=15)
    for c in r.cameras:
        say("  idx=%-2d name=%-18s actor=%s" % (c.index, c.name, c.actor_path))
except Exception as e:
    say("  GetCameras 失败:", type(e).__name__, e)

say("")
say("=" * 70)
say("B. 引擎 MCP get_all_actors() —— 只列名字含 camera/相机 的")
say("=" * 70)
m = OrcaMcp()
m.connect()
say("sim:", call_text(m, "get_simulation_state", {})[:80])
try:
    d = json.loads(call_text(m, "get_all_actors", {}, timeout=40))
    say("  actor 总数:", len(d))
    n = 0
    for k, v in sorted(d.items()):
        if "camera" in k.lower() or "cam" in os.path.basename(k).lower():
            n += 1
            pos = v.get("transform.position") or v.get("world_transform.position")
            rot = v.get("transform.rotation") or v.get("world_transform.rotation")
            sc = v.get("transform.scale") or v.get("world_transform.scale")
            par = v.get("parent") or v.get("parent_path")
            say("  %-34s pos=%s rot=%s scale=%s parent=%s" % (
                k,
                [round(float(x), 4) for x in pos] if pos else None,
                [round(float(x), 3) for x in rot] if rot else None, sc, par))
    say("  相机相关 actor 数:", n)
    if n == 0:
        say("  --- 引擎场景里没有任何名字带 camera 的 actor ---")
except Exception as e:
    say("  get_all_actors 失败:", type(e).__name__, e)

say("")
say("=" * 70)
say("C. 视口三台机载相机的世界位姿（50151 SetActiveCamera + MCP get_viewport_transform）")
say("=" * 70)
for idx, nm in ((1, "camera_head"), (2, "camera_left"), (3, "camera_right")):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": idx})
        import time
        time.sleep(1.2)
        t = json.loads(call_text(m, "get_viewport_transform", {}))
        tr = t.get("transform", t)
        say("  idx%d %-13s pos=%s rot=%s scale=%s" % (
            idx, nm,
            [round(float(x), 4) for x in (tr.get("position") or [])],
            [round(float(x), 3) for x in (tr.get("rotation") or [])],
            tr.get("scale")))
    except Exception as e:
        say("  idx%d 失败: %s %s" % (idx, type(e).__name__, e))
try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass

say("")
say("=" * 70)
say("D. 视口相机自带的参数 get_viewport_camera_info")
say("=" * 70)
for idx in (1, 2, 3):
    try:
        say("  idx%d: %s" % (idx, call_text(m, "get_viewport_camera_info", {"index": idx})[:400]))
    except Exception as e:
        say("  idx%d 失败: %s %s" % (idx, type(e).__name__, e))

with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("\nDONE", OUT)
