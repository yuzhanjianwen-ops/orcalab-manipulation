"""robot_cam_enable.py —— 一键打开/关闭机器人自带的三台相机。

重大发现（2026-10-02）
--------------------
机器人资产 g1_omnipicker_usda 里**本来就有三台相机**，
挂在正确的层级上，属性完整，端口互不冲突：

    Entity 路径                     ColorPort  DepthPort  StreamID       Enable
    .../cameras/camera_head         7070       7071       HcllK6r4aS1p   False
    .../cameras/camera_left         7080       7081       mQNGGARXXh5V   False
    .../cameras/camera_right        7090       7091       A69JyvaP91zO   False

它们挂在：
    camera_head   -> head_link2 / camera_head_body1 / camera_head_body2 / cameras
    camera_left   -> arm_l_end_link / camera_left_body1 / camera_left_body2 / cameras
    camera_right  -> arm_r_end_link / camera_right_body1 / camera_right_body2 / cameras

**只需要把 Enable 从 False 改成 True。**

用法
----
    & "C:\\Users\\86322\\.conda\\envs\\orcalab\\python.exe" -X utf8 -u robot_cam_enable.py --status
    & "...python.exe" -X utf8 -u robot_cam_enable.py --on
    & "...python.exe" -X utf8 -u robot_cam_enable.py --off
"""
from __future__ import annotations
import argparse, json, os, socket, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from orca_mcp import OrcaMcp  # noqa

ROBOT = "/dual_arm_collaborative_service_robot_1"
CAMS = ("camera_head", "camera_left", "camera_right")
PORTS = {"camera_head": (7070, 7071), "camera_left": (7080, 7081),
         "camera_right": (7090, 7091)}


def call(m, name, args=None, t=60):
    r = m.rpc("tools/call", {"name": name, "arguments": args or {}}, timeout=t)
    try:
        return "".join(x.get("text", "") for x in r["result"]["content"])
    except Exception:
        return json.dumps(r, ensure_ascii=False)


def port_open(p, t=0.5):
    s = socket.socket(); s.settimeout(t)
    try:
        s.connect(("127.0.0.1", p)); return True
    except Exception:
        return False
    finally:
        s.close()


def read(m, ent):
    r = call(m, "get_actor_properties", {"asset_path": "%s/%s" % (ROBOT, ent)})
    try:
        groups = json.loads(r)
    except Exception:
        return None
    d = {}
    for g in groups:
        for p in g.get("properties", []):
            d[p["name"]] = p["value"]
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--on", action="store_true")
    ap.add_argument("--off", action="store_true")
    a = ap.parse_args()

    m = OrcaMcp(timeout=60)
    m.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "robot-cam", "version": "1"}})

    print("=" * 70)
    print("机器人自带相机")
    print("=" * 70)
    sim = call(m, "get_simulation_state")
    print("仿真:", sim)

    rows = []
    for e in CAMS:
        d = read(m, e)
        if not d:
            print("  %s: 读不到（场景里没有机器人？）" % e)
            continue
        rows.append((e, d))
        cp, dp = PORTS[e]
        print("\n%-14s Enable=%-6s Color=%-6s Depth=%-6s" % (
            e, d.get("Enable"), d.get("ColorCamera"), d.get("DepthCamera")))
        print("    ColorPort=%s DepthPort=%s StreamID=%s FOV=%s %sx%s" % (
            d.get("ColorPort"), d.get("DepthPort"), d.get("StreamID"),
            d.get("VerticalFieldOfViewDeg"), d.get("Width"), d.get("Height")))

    if a.status or (not a.on and not a.off):
        print("\n端口状态（注: 7070 系列是 WebSocket，TCP 测不准属正常）:")
        for e in CAMS:
            cp, dp = PORTS[e]
            print("   %-14s %d=%s %d=%s" % (e, cp, port_open(cp), dp, port_open(dp)))
        return 0

    val = True if a.on else False
    print("\n--- 设置 Enable=%s ---" % val)
    for e in CAMS:
        for prop in ("Enable", "ColorCamera", "DepthCamera"):
            r = call(m, "set_actor_properties",
                     {"asset_path": "%s/%s" % (ROBOT, e),
                      "property_name": prop, "property_value": val})
            ok = "success" in r
            print("   %-14s %-12s %s" % (e, prop, "OK" if ok else r[:60]))

    print("\n提示：属性改动要生效，需要在 OrcaStudio 里")
    print("  · 停止仿真 → 重新打开布局 → 再启动仿真")
    print("  · 然后跑 camera_doctor.py 看 ncam 是否 > 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
