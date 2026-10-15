# -*- coding: utf-8 -*-
"""cam3d_view.py - 三视角可视化（从 Studio 实时读机器人相机的真实世界位姿）

原理
----
机器人 prefab 自带 3 个相机实体（camera_head / camera_left / camera_right）。
它们在 Studio 里已注册为"视口相机"，所以可以这样拿到**真实世界位姿**：

  1) 连 Studio 编辑服务 127.0.0.1:50151
  2) GetCameras()                       -> 相机名 -> index
  3) SetActiveCamera(index)             -> 把视口切到该相机
  4) GetViewportCameraTransform()       -> 读回它的世界 pos + quat  ← 真实位姿
  5) quat -> roll/pitch/yaw，再用 MCP get_view_png_from_transform 渲染出图

注意：GetCameraPNG（相机真实出流）需要 50051 仿真端加载同一场景并步进；
      若仿真里没有这台机器人，就退化成"用真实位姿渲染"（本脚本默认方式）。

用法
----
  python cam3d_view.py                     自动读真实位姿并渲染 3 张 + 三联图
  python cam3d_view.py --list              只打印每个相机的真实世界位姿
  python cam3d_view.py --pitch-extra -10   在真实朝向上再俯仰 10 度
  python cam3d_view.py --use-quat          用相机自带朝向（不做 look-at）
  python cam3d_view.py --target 17.15,-2.94,1.24
  python cam3d_view.py --manual            用下面 MANUAL 手填位姿（不连 Studio）
  python cam3d_view.py --save-poses        把读到的真实位姿写进 poses.json
"""
import os
import sys
import json
import math
import base64
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
EDIT_ADDR = "127.0.0.1:50151"
MCP_HOST, MCP_PORT = "127.0.0.1", 12345

# ==================== 可调参数 ====================
CAMERA_ORDER = ["camera_head", "camera_left", "camera_right"]

# 看向的世界点。None = 自动取桌面/物体中心；也可写 [17.15, -2.94, 1.24]
LOOK_TARGET = None
TARGET_HINT = ["/Group/Interactive_Objcets", "/Group/Static_Objcets/Table"]

PITCH_EXTRA = 0.0        # 额外俯仰(度)，负值 = 往下看
YAW_EXTRA = 0.0          # 额外偏航(度)
USE_CAMERA_QUAT = False  # True = 用相机自带朝向，不 look-at

OUT_INDEX_BASE = 4100    # MCP 渲染文件名后缀起点
COMPOSITE = True

# 仅 --manual 时使用：手填世界位姿
MANUAL = {
    "camera_head":  {"position": [18.458, -3.411, 1.222], "rotation": [0.0, -20.0, 0.0]},
    "camera_left":  {"position": [18.351, -2.635, 1.110], "rotation": [0.0, -30.0, 0.0]},
    "camera_right": {"position": [18.355, -4.189, 1.078], "rotation": [0.0, -30.0, 0.0]},
}
# ==================================================


# ---------- 数学 ----------
def quat_to_euler_deg(qx, qy, qz, qw):
    """四元数 -> [roll, pitch, yaw]（度，XYZ 外旋/ZYX 内旋约定）。"""
    sinr = 2.0 * (qw * qx + qy * qz)
    cosr = 1.0 - 2.0 * (qx * qx + qy * qy)
    roll = math.atan2(sinr, cosr)

    sinp = 2.0 * (qw * qy - qz * qx)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.asin(sinp)

    siny = 2.0 * (qw * qz + qx * qy)
    cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
    yaw = math.atan2(siny, cosy)
    return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]


def look_at_rotation(pos, tgt, pitch_extra=0.0, yaw_extra=0.0):
    """相机放 pos 看向 tgt，返回 [roll, pitch, yaw]（度）。"""
    d = [tgt[i] - pos[i] for i in range(3)]
    n = math.sqrt(sum(v * v for v in d))
    if n < 1e-9:
        return [0.0, 0.0, 0.0]
    dx, dy, dz = [v / n for v in d]
    yaw = math.degrees(math.atan2(dy, dx)) + yaw_extra
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, dz)))) + pitch_extra
    return [0.0, pitch, yaw]


# ---------- Studio 真实位姿 ----------
def read_real_poses(want=None):
    """返回 {camera_name: {"position": [...], "rotation": [...], "quat": [...]}}"""
    import grpc
    import orcalab.protos.edit_service_pb2 as ep
    import orcalab.protos.edit_service_pb2_grpc as epg

    stub = epg.GrpcServiceStub(grpc.insecure_channel(EDIT_ADDR))
    cams = list(stub.GetCameras(ep.GetCamerasRequest(), timeout=10).cameras)
    name_to_index = {}
    for c in cams:
        name_to_index[c.name] = c.index

    order = want or CAMERA_ORDER
    poses = {}
    for name in order:
        if name not in name_to_index:
            print("  [x] %s 未在 Studio 注册；已注册: %s" % (name, sorted(name_to_index)))
            continue
        idx = name_to_index[name]
        stub.SetActiveCamera(ep.SetActiveCameraRequest(index=idx), timeout=10)
        t = stub.GetViewportCameraTransform(
            ep.GetViewportCameraTransformRequest(), timeout=10).transform
        pos = [float(v) for v in t.pos]
        quat = [float(v) for v in t.quat]
        euler = quat_to_euler_deg(*quat)
        poses[name] = {"index": idx, "position": pos, "quat": quat, "rotation": euler}
    return poses


# ---------- MCP 渲染 ----------
def get_mcp():
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
    from orca_mcp import OrcaMcp
    m = OrcaMcp(MCP_HOST, MCP_PORT, timeout=180)
    m.connect()
    return m


def render(mcp, name, position, rotation, index):
    r = mcp.call("get_view_png_from_transform",
                 {"position": list(position), "rotation": list(rotation), "index": index})
    if "error" in r:
        print("  [x] %s: %s" % (name, r["error"]))
        return None
    content = r.get("result", {}).get("content", [])
    if not content or content[0].get("type") != "image":
        print("  [x] %s 返回非图像" % name)
        return None
    data = base64.b64decode(content[0]["data"])
    path = os.path.join(OUT_DIR, "%s.png" % name)
    with open(path, "wb") as f:
        f.write(data)
    print("  [ok] %-13s pos=%s rot=%s" % (
        name, [round(v, 3) for v in position], [round(v, 1) for v in rotation]))
    return path


def composite(paths):
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        print("  [warn] 无 PIL，跳过拼图: %s" % e)
        return
    imgs = [(os.path.basename(p), Image.open(p).convert("RGB")) for p in paths if p]
    if not imgs:
        return
    w, h = imgs[0][1].size
    comp = Image.new("RGB", (w * len(imgs), h + 28), (20, 20, 20))
    d = ImageDraw.Draw(comp)
    for i, (nm, im) in enumerate(imgs):
        comp.paste(im.resize((w, h)), (i * w, 28))
        d.text((i * w + 8, 8), nm, fill=(255, 255, 255))
    out = os.path.join(OUT_DIR, "cam3d_composite.png")
    comp.save(out)
    print("  [ok] 三联图 -^ %s" % out)


def auto_target(mcp):
    for ap in TARGET_HINT:
        try:
            d = json.loads(_call_text(mcp, "get_actor_asset_aabb", {"actor_path": ap}))
            bb = d.get("aabb")
            if bb and len(bb) == 6:
                return [(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2]
        except Exception:
            continue
    return [17.15, -2.94, 1.24]


def _call_text(mcp, name, args):
    from orca_mcp import call_text
    return call_text(mcp, name, args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只打印真实位姿，不渲染")
    ap.add_argument("--manual", action="store_true", help="用手填位姿，不连 Studio")
    ap.add_argument("--use-quat", action="store_true", help="用相机自带朝向")
    ap.add_argument("--target", default=None, help="看向点 x,y,z")
    ap.add_argument("--pitch-extra", type=float, default=PITCH_EXTRA)
    ap.add_argument("--yaw-extra", type=float, default=YAW_EXTRA)
    ap.add_argument("--save-poses", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.manual:
        poses = {n: {"position": MANUAL[n]["position"], "rotation": MANUAL[n]["rotation"],
                     "quat": None, "index": -1} for n in CAMERA_ORDER if n in MANUAL}
        print("== 手填位姿模式 ==")
    else:
        print("== 从 Studio 读真实世界位姿 ==")
        poses = read_real_poses()

    for n in CAMERA_ORDER:
        if n in poses:
            p = poses[n]
            print("  %-13s index=%-2s world_pos=%s  quat=%s  euler=%s" % (
                n, p.get("index"), [round(v, 4) for v in p["position"]],
                [round(v, 4) for v in (p.get("quat") or [])],
                [round(v, 2) for v in p["rotation"]]))

    if args.save_poses:
        with open(os.path.join(OUT_DIR, "poses.json"), "w", encoding="utf-8") as f:
            json.dump(poses, f, ensure_ascii=False, indent=2)
        print("  已保存 poses.json")

    if args.list:
        return 0

    mcp = get_mcp()
    target = [float(x) for x in args.target.split(",")] if args.target else (
        LOOK_TARGET or auto_target(mcp))
    print("  看向目标:", [round(v, 3) for v in target])

    paths = []
    for i, n in enumerate(CAMERA_ORDER):
        if n not in poses:
            continue
        p = poses[n]
        if args.use_quat or not p.get("quat"):
            rot = list(p["rotation"])
        else:
            rot = look_at_rotation(p["position"], target,
                                   args.pitch_extra, args.yaw_extra)
        paths.append(render(mcp, n, p["position"], rot, OUT_INDEX_BASE + i))

    if COMPOSITE:
        composite(paths)
    ok = [x for x in paths if x]
    print("完成：%d/%d" % (len(ok), len(CAMERA_ORDER)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
