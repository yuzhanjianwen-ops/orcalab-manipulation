# -*- coding: utf-8 -*-
"""标定：OrcaStudio 主视口 index 0..5 分别对应哪一台相机。

判定依据（三条互相印证）：
  1. get_viewport_transform() 返回的 scale —— 1.0=自由相机；1.695=挂在机器人上的机载相机
  2. 视口相机位姿 vs 场景里相机 actor 的世界位姿（get_all_actors）—— 距离最近即同一台
  3. 与三路机载推流(7070/7080/7090)画面的 NCC 相关（可选）

产出： _fov_probe/vpcam2/  下 gl_idxN.png（编辑器 3D 视口裁切）+ 标注拼图 + report.json
结束前把视口还原到起始 index。
"""
import os, sys, io, time, json, ctypes, shutil
from ctypes import wintypes

HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageGrab, ImageDraw
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "vpcam2")
os.makedirs(OUT, exist_ok=True)

ROBOT_SCALE = 1.695
u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))


def find_orca():
    hw = []

    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        n = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(h, n, 512)
        if n.value.strip().startswith("26.8.1"):
            hw.append(h)
        return True

    u.EnumWindows(CB(cb), None)
    return hw[0] if hw else None


def grab(h):
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.7)
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))


def gl_crop(im):
    """从整窗截图里裁出右侧 3D 视口区（去左侧面板 + 工具栏）。"""
    W, H = im.size
    a = np.asarray(im, dtype=np.float32)
    panel = np.median(a[300:min(900, H), 10:60, :].reshape(-1, 3), axis=0)
    diff = np.abs(a - panel).mean(axis=2)
    is3d = diff > 18
    col_frac = is3d.mean(axis=0)
    x0 = W
    for x in range(W // 2, 0, -1):
        if col_frac[x] < 0.35 and col_frac[max(0, x - 30):x].mean() < 0.35:
            x0 = x + 1
            break
    row_frac = is3d[:, x0:].mean(axis=1)
    y0 = H
    for y in range(H // 2, 0, -1):
        if row_frac[y] < 0.35 and row_frac[max(0, y - 25):y].mean() < 0.35:
            y0 = y + 1
            break
    return im.crop((x0, y0, W, H))


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


m = OrcaMcp()
m.connect()
print("仿真状态:", call_text(m, "get_simulation_state", {})[:120])

# --- 场景里的相机 actor ---
cam_actors = {}
d = json.loads(call_text(m, "get_all_actors", {}))
for path, info in d.items():
    nm = (info.get("name") or "").lower()
    if "camera" in nm:
        p = info.get("world_transform", {}).get("position") or info.get("transform.position")
        if p:
            cam_actors[path] = [float(x) for x in p]
print("场景内相机 actor：")
for k, v in cam_actors.items():
    print("   %-24s %s" % (k, [round(x, 3) for x in v]))

# --- 起始视口，便于还原 ---
start = json.loads(call_text(m, "get_viewport_camera_info", {}))["transform"]["position"]
start_idx = None

h = find_orca()
print("OrcaStudio hwnd:", h)

rows = []
for idx in range(6):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": idx})
        time.sleep(1.0)
        r = json.loads(call_text(m, "get_viewport_transform", {}))
        t = r.get("transform", r)
        pos = [round(float(x), 3) for x in t.get("position", [])]
        sc = float(t.get("scale", -1))
        if start_idx is None and dist(t["position"], start) < 1e-4:
            start_idx = idx

        # 身份判定
        if abs(sc - 1.0) < 0.01:
            who, extra = "自由相机(编辑器默认)", ""
        elif abs(sc - ROBOT_SCALE) < 0.01:
            best, bd = None, 1e9
            for k, v in cam_actors.items():
                dd = dist(pos, v)
                if dd < bd:
                    best, bd = k, dd
            who = "机载相机"
            extra = "≈ %s (Δ%.3fm)" % (best, bd) if best and bd < 0.35 else "未匹配到场景相机 actor"
        else:
            who, extra = "未知(scale=%.3f)" % sc, ""

        p = os.path.join(OUT, "gl_idx%d.png" % idx)
        if h:
            im = grab(h)
            im.save(os.path.join(OUT, "editor_idx%d.png" % idx))
            gl_crop(im).save(p)
        rows.append({"index": idx, "scale": sc, "pos": pos, "who": who, "note": extra})
        print("  idx %d  scale=%.3f  %-16s pos=%s  %s" % (idx, sc, who, pos, extra))
    except Exception as e:
        print("  idx %d ERR %s" % (idx, str(e)[:100]))

if start_idx is not None:
    call_text(m, "set_viewport_camera", {"camera_index": start_idx})
    print("视口已还原到 idx %d" % start_idx)

with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
    json.dump({"cam_actors": cam_actors, "rows": rows}, f, ensure_ascii=False, indent=2)

# --- 标注拼图 ---
TH, GAP, LAB = 300, 10, 34
tiles = []
for r in rows:
    p = os.path.join(OUT, "gl_idx%d.png" % r["index"])
    if not os.path.exists(p):
        continue
    im = Image.open(p).convert("RGB")
    w, hh = im.size
    tiles.append((r, im.resize((max(1, int(w * TH / hh)), TH), Image.LANCZOS)))
if tiles:
    cols = 3
    rows_n = (len(tiles) + cols - 1) // cols
    W = cols * tiles[0][1].width + GAP * (cols + 1)
    H = 30 + rows_n * (TH + LAB) + GAP
    M = Image.new("RGB", (W, H), (16, 16, 16))
    dr = ImageDraw.Draw(M)
    dr.text((GAP, 8), "Editor viewport index 0..5 -- which camera each one is", fill=(255, 220, 0))
    for k, (r, im) in enumerate(tiles):
        c, rr = k % cols, k // cols
        x = GAP + c * (im.width + GAP)
        y = 30 + rr * (TH + LAB)
        dr.text((x + 2, y), "idx%d  scale=%.3f  %s  pos[%s]  %s" % (
            r["index"], r["scale"], r["who"],
            ",".join("%.2f" % v for v in r["pos"]), r["note"]), fill=(0, 255, 128))
        M.paste(im, (x, y + LAB - 14))
    o = os.path.join(OUT, "viewport_index_camera_map.png")
    M.save(o)
    print("拼图:", o, M.size)
