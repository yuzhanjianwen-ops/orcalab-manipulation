# -*- coding: utf-8 -*-
"""camera_verify.py —— 机器人自带相机（camera_head/left/right）验证脚本。

用法：
  & "<你的orcalab环境>\\python.exe" -X utf8 -u camera_verify.py            # 看状态
  & "...python.exe" -X utf8 -u camera_verify.py --on                                            # 开相机
  & "...python.exe" -X utf8 -u camera_verify.py --grab                                           # 取图
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from orca_mcp import OrcaMcp, call_text  # noqa: E402

ROBOT = "/dual_arm_collaborative_service_robot_1"
CAMS = ("camera_head", "camera_left", "camera_right")
DEFAULT_PORTS = {
    "camera_head": (7070, 7071),
    "camera_left": (7080, 7081),
    "camera_right": (7090, 7091),
}
OUT_DIR = os.path.join(HERE, "camera_shots")


def port_open(p, t=0.6):
    s = socket.socket()
    s.settimeout(t)
    try:
        s.connect(("127.0.0.1", p))
        return True
    except Exception:
        return False
    finally:
        s.close()


def read_props(m, entity):
    raw = call_text(m, "get_actor_properties",
                    {"asset_path": "%s/%s" % (ROBOT, entity)})
    try:
        groups = json.loads(raw)
    except Exception:
        return None
    out = {}
    for g in groups:
        for p in g.get("properties", []):
            out[p["name"]] = p["value"]
    return out


def set_prop(m, entity, name, value):
    return call_text(m, "set_actor_properties",
                     {"asset_path": "%s/%s" % (ROBOT, entity),
                      "property_name": name,
                      "property_value": value})


def cmd_status(m):
    print("=" * 74)
    print("仿真状态")
    print("=" * 74)
    print("  ", call_text(m, "get_simulation_state"))

    print()
    print("=" * 74)
    print("三台相机属性")
    print("=" * 74)
    for e in CAMS:
        d = read_props(m, e)
        if not d:
            print("  %s: 读不到" % e)
            continue
        print()
        print("  [%s]" % e)
        for k in ("Enable", "ColorCamera", "DepthCamera", "NormalCamera",
                  "UseNvEnc", "Width", "Height", "VerticalFieldOfViewDeg",
                  "ColorPort", "DepthPort", "StreamID", "IsRecording"):
            if k in d:
                print("      %-22s = %s" % (k, d[k]))

    print()
    print("=" * 74)
    print("端口监听状态")
    print("=" * 74)
    for e in CAMS:
        cp, dp = DEFAULT_PORTS[e]
        print("  %-14s color %-5d %-10s depth %-5d %s" % (
            e, cp, "OPEN" if port_open(cp) else "closed",
            dp, "OPEN" if port_open(dp) else "closed"))
    print()
    print("  端口 closed 表示推流未开启；Enable=True 后一般要重启仿真才生效。")


def cmd_on(m, val=True):
    print("=" * 74)
    print("设置 Enable=%s / ColorCamera=%s" % (val, val))
    print("=" * 74)
    for e in CAMS:
        for prop in ("Enable", "ColorCamera"):
            r = set_prop(m, e, prop, val)
            ok = ("success" in r.lower()) or ("true" in r.lower())
            print("  %-14s %-14s -> %s" % (e, prop, "OK" if ok else r[:70]))
    print()
    print("接下来：停止仿真 -> 重新启动仿真 -> 跑 --status 看端口 -> 跑 --grab")


def cmd_grab(m, timeout_s=8.0):
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 74)
    print("取图（WebSocket）")
    print("=" * 74)
    try:
        from orca_gym.sensor.rgbd_camera import CameraWrapper
    except Exception as ex:
        print("  导入 CameraWrapper 失败:", ex)
        return
    for e in CAMS:
        cp, _dp = DEFAULT_PORTS[e]
        if not port_open(cp):
            print("  %-14s 端口 %d 未监听，跳过" % (e, cp))
            continue
        print("  %-14s 连接 ws://localhost:%d ..." % (e, cp))
        cam = CameraWrapper(name=e, port=cp)
        cam.start()
        t0 = time.time()
        got = False
        while time.time() - t0 < timeout_s:
            if cam.is_first_frame_received():
                got = True
                break
            time.sleep(0.1)
        if got:
            frame, idx = cam.get_frame(format="rgb24")
            out = os.path.join(OUT_DIR, "%s.png" % e)
            try:
                import cv2
                cv2.imwrite(out, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                print("      OK frame_index=%s shape=%s -> %s" % (idx, frame.shape, out))
            except Exception as ex:
                print("      OK shape=%s 保存失败: %s" % (frame.shape, ex))
        else:
            print("      超时：%.1fs 内没收到首帧" % timeout_s)
        cam.stop()
    print()
    print("  图片目录:", OUT_DIR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--on", action="store_true")
    ap.add_argument("--off", action="store_true")
    ap.add_argument("--grab", action="store_true")
    a = ap.parse_args()
    m = OrcaMcp(timeout=90)
    m.connect()
    if a.on:
        cmd_on(m, True)
    elif a.off:
        cmd_on(m, False)
    elif a.grab:
        cmd_grab(m)
    else:
        cmd_status(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
