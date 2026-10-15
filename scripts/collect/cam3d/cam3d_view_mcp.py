# -*- coding: utf-8 -*-
"""cam3d_view_mcp.py —— 三视角可视化（从 MCP 实时读机器人相机实体的真实世界位姿）

流程
----
1. 连 OrcaStudio MCP（127.0.0.1:12345），自动找到带 camera_head 的机器人 actor。
2. 用 get_entity_hierarchy 找到 camera_head / camera_left / camera_right 的完整
   实体路径，再沿祖先链把每级 local translate/rotate 累乘，得到相机的**世界位置**。
3. 旋转用 look-at：相机放在真实位置，朝 CAMERA_TARGET（工作区）看。
   （比直接换算欧拉角稳，不受 OrcaStudio 欧拉约定影响。）
4. 用 MCP get_view_png_from_transform 渲染 3 张图 + 一张三联图。

用法
----
  python cam3d_view_mcp.py
  python cam3d_view_mcp.py --actor /robot_cam_test
  python cam3d_view_mcp.py --target 17.3,-3.47,1.41
  python cam3d_view_mcp.py --manual             # 用 CAMERAS 里手填的位姿，不读 MCP
  python cam3d_view_mcp.py --pitch -25 --yaw-mode -1
"""
import os, sys, json, math, base64, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECT = os.path.abspath(os.path.join(HERE, ".."))
if COLLECT not in sys.path:
    sys.path.insert(0, COLLECT)

from orca_mcp import OrcaMcp, call_text  # noqa: E402

# ========================= 可调参数 =========================
MCP_HOST, MCP_PORT = "127.0.0.1", 12345
CAMERA_NAMES = ["camera_head", "camera_left", "camera_right"]

# 相机看向的世界坐标目标点（工作区/桌面）。默认自动取桌面上物体中心。
CAMERA_TARGET = None            # None=自动；也可写 [17.3, -3.47, 1.41]
TARGET_HINT_ACTORS = ["/Group/Interactive_Objcets", "/Group/Static_Objcets/Table"]

PITCH_SIGN = -1.0               # look-at 俯仰符号（自动模式下会自动校正）
PITCH_EXTRA = 0.0               # 额外俯仰(度)
YAW_OFFSET = 0.0                # 额外偏航(度)

OUT_DIR = os.path.join(HERE, "out")
OUT_INDEX_BASE = 4000
COMPOSITE = True

# 只有 --manual 时才用：手填世界位姿
CAMERAS = {
    "camera_head":  {"position": [0.258, -0.011, 0.573], "rotation": [0.0, -20.0, 0.0]},
    "camera_left":  {"position": [-0.194, 0.357, 0.462], "rotation": [0.0, -30.0, 0.0]},
    "camera_right": {"position": [-0.198, -0.337, 0.429], "rotation": [0.0, -30.0, 0.0]},
}
# ===========================================================


# ---------------- 数学 ----------------
def euler_xyz_to_mat(rx, ry, rz):
    x, y, z = map(math.radians, (rx, ry, rz))
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    return [
        [cy * cz, cz * sx * sy - cx * sz, cx * cz * sy + sx * sz],
        [cy * sz, cx * cz + sx * sy * sz, -cz * sx + cx * sy * sz],
        [-sy, cy * sx, cx * cy],
    ]


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_vec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def vec_add(a, b):
    return [a[i] + b[i] for i in range(3)]


def look_at_rotation(pos, tgt, pitch_sign=PITCH_SIGN, yaw_off=0.0, pitch_extra=0.0):
    """世界位置 pos 看向 tgt，返回 [roll, pitch, yaw] 度（OrcaStudio 约定）。"""
    d = [tgt[i] - pos[i] for i in range(3)]
    n = math.sqrt(sum(v * v for v in d))
    if n < 1e-9:
        return [0.0, 0.0, 0.0]
    dx, dy, dz = [v / n for v in d]
    yaw = math.degrees(math.atan2(dy, dx)) + yaw_off
    pitch = pitch_sign * math.degrees(math.asin(max(-1.0, min(1.0, dz)))) + pitch_extra
    return [0.0, pitch, yaw]


# ---------------- MCP 读取 ----------------
def get_hierarchy(mcp, actor_path):
    return json.loads(call_text(mcp, "get_entity_hierarchy", {"asset_path": actor_path}))


def index_paths(tree):
    acc = {}

    def walk(n):
        acc[n.get("entity_path")] = n.get("name")
        for c in n.get("children", []):
            walk(c)

    walk(tree)
    return acc


def find_path_by_name(tree, name):
    found = []

    def walk(n):
        if n.get("name") == name:
            found.append(n.get("entity_path"))
        for c in n.get("children", []):
            walk(c)

    walk(tree)
    return found[0] if found else None


def read_local_transform(mcp, actor_path, entity_name):
    raw = call_text(mcp, "get_actor_properties", {"asset_path": actor_path + "/" + entity_name})
    try:
        groups = json.loads(raw)
    except Exception:
        return None
    if not isinstance(groups, list):
        return None
    info = {"translate": [0.0, 0.0, 0.0], "rotate": [0.0, 0.0, 0.0]}
    for g in groups:
        for p in g.get("properties", []):
            nm, v = p.get("name"), p.get("value")
            if nm == "translate.x":
                info["translate"][0] = v
            elif nm == "translate.y":
                info["translate"][1] = v
            elif nm == "translate.z":
                info["translate"][2] = v
            elif nm == "rotate.x":
                info["rotate"][0] = v
            elif nm == "rotate.y":
                info["rotate"][1] = v
            elif nm == "rotate.z":
                info["rotate"][2] = v
            elif nm in ("VerticalFieldOfViewDeg", "Width", "Height", "ColorPort",
                        "DepthPort", "Enable"):
                info[nm] = v
    return info


def world_position_of(mcp, actor_path, entity_path, path_names):
    """沿 entity_path 逐级累乘 local translate，返回世界位置。"""
    segs = entity_path.split("/")
    pos = [0.0, 0.0, 0.0]
    rot = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for i in range(2, len(segs) + 1):
        p = "/".join(segs[:i])
        name = path_names.get(p)
        if not name:
            continue
        info = read_local_transform(mcp, actor_path, name)
        if info is None:
            continue
        lm = euler_xyz_to_mat(*info["rotate"])
        pos = vec_add(mat_vec(rot, info["translate"]), pos)
        rot = mat_mul(rot, lm)
    return pos


def find_robot(mcp, explicit=None):
    if explicit:
        return explicit, get_hierarchy(mcp, explicit)
    for p in json.loads(call_text(mcp, "get_all_actors")):
        if p == "/":
            continue
        try:
            t = get_hierarchy(mcp, p)
        except Exception:
            continue
        if find_path_by_name(t, "camera_head"):
            return p, t
    return None, None


def auto_target(mcp):
    for ap in TARGET_HINT_ACTORS:
        try:
            raw = call_text(mcp, "get_actor_asset_aabb", {"actor_path": ap})
            d = json.loads(raw)
            bb = d.get("aabb")
            if bb and len(bb) == 6:
                return [(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2]
        except Exception:
            continue
    return [0.25, 0.0, 0.05]


# ---------------- 渲染 ----------------
def render(mcp, name, position, rotation, index, out_dir):
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
    path = os.path.join(out_dir, "%s.png" % name)
    with open(path, "wb") as f:
        f.write(data)
    print("  [ok] %-13s pos=%s rot=%s -> %s (%d B)" % (
        name, [round(v, 3) for v in position], [round(v, 1) for v in rotation], path, len(data)))
    return path


def composite(paths, out_dir):
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
    out = os.path.join(out_dir, "cam3d_composite.png")
    comp.save(out)
    print("  [ok] 三联图 -> %s" % out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", default=None, help="机器人 actor 路径，默认自动查找")
    ap.add_argument("--target", default=None, help="看向的世界点 x,y,z，默认自动")
    ap.add_argument("--manual", action="store_true", help="用 CAMERAS 里手填的位姿")
    ap.add_argument("--pitch", type=float, default=PITCH_EXTRA, help="额外俯仰(度)")
    ap.add_argument("--pitch-sign", type=float, default=PITCH_SIGN)
    ap.add_argument("--yaw-offset", type=float, default=YAW_OFFSET)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.manual:
        target = None
        if args.target:
            target = [float(x) for x in args.target.split(",")]
        mcp = OrcaMcp(MCP_HOST, MCP_PORT, timeout=180)
        print("MCP:", mcp.connect())
        paths = []
        for i, cam in enumerate(CAMERA_NAMES):
            c = CAMERAS[cam]
            paths.append(render(mcp, cam, c["position"], c["rotation"], OUT_INDEX_BASE + i, OUT_DIR))
        if COMPOSITE:
            composite(paths, OUT_DIR)
        return 0

    mcp = OrcaMcp(MCP_HOST, MCP_PORT, timeout=180)
    print("MCP:", mcp.connect())
    actor_path, tree = find_robot(mcp, args.actor)
    if not actor_path:
        print("没找到带 camera_head 的机器人 actor。用 --actor 指定，或 --manual。")
        return 1
    print("机器人 actor:", actor_path)

    path_names = index_paths(tree)
    target = [float(x) for x in args.target.split(",")] if args.target else (CAMERA_TARGET or auto_target(mcp))
    print("看向目标:", [round(v, 3) for v in target])

    paths = []
    for i, cam in enumerate(CAMERA_NAMES):
        cp = find_path_by_name(tree, cam)
        if not cp:
            print("  [skip] %s 不在实体树里" % cam)
            continue
        pos = world_position_of(mcp, actor_path, cp, path_names)
        rot = look_at_rotation(pos, target, args.pitch_sign, args.yaw_offset, args.pitch)
        info = read_local_transform(mcp, actor_path, cam) or {}
        print("  %s: FOV=%s 端口=%s/%s Enable=%s" % (
            cam, info.get("VerticalFieldOfViewDeg"), info.get("ColorPort"),
            info.get("DepthPort"), info.get("Enable")))
        paths.append(render(mcp, cam, pos, rot, OUT_INDEX_BASE + i, OUT_DIR))

    if COMPOSITE:
        composite(paths, OUT_DIR)
    ok = [p for p in paths if p]
    print("完成：%d/%d" % (len(ok), len(CAMERA_NAMES)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
