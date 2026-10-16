# -*- coding: utf-8 -*-
"""判定 OrcaStudio 视口 index 0..6 各自对应哪台相机 —— 不跑仿真、可逆。

方法（不依赖任何猜测）
======================
1) 逐个 index 渲染一帧 -> base_idxN.png，并记录该 index 的视口相机世界位姿；
2) 把场景里三台静置相机 (head_camera_1 / wrist_camera_l / wrist_camera_r)
   整体搬到高空 15m 且彼此分开；
3) 再逐个 index 渲染 -> moved_idxN.png；
4) 逐 index 比较前后差异：**差异大的 index 就是静置相机**，
   没变化的 index 就是机器人机载相机（跟着机器人，不受场景相机影响）；
5) 恢复三台静置相机的原始位姿。

产出： _fov_probe/camid/  （base_idxN.png / moved_idxN.png / result.json / report.txt）
"""
import os
import sys
import io
import json
import time
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "camid")
os.makedirs(OUT, exist_ok=True)

STATIC = ("/head_camera_1", "/wrist_camera_l", "/wrist_camera_r")
# 搬走后的目标位姿：高空、彼此拉开、朝下看
MOVED = {
    "/head_camera_1": ([18.0, -3.0, 18.0], [-80.0, 0.0, 0.0]),
    "/wrist_camera_l": ([14.0, -8.0, 18.0], [-80.0, 0.0, 0.0]),
    "/wrist_camera_r": ([22.0, 2.0, 18.0], [-80.0, 0.0, 0.0]),
}

u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))


def find_orca():
    hw = []

    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        n = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(h, n, 512)
        if n.value.strip().startswith("26."):
            hw.append(h)
        return True

    u.EnumWindows(CB(cb), None)
    return hw[0] if hw else None


def grab(h):
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.9)
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))


def gl_crop(im):
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


def crop(im, size=(320, 320)):
    return np.asarray(im.convert("L").resize(size, Image.LANCZOS), dtype=np.float32)


log = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log.append(s)


m = OrcaMcp()
m.connect()
state = call_text(m, "get_simulation_state", {})
say("sim:", state[:90])
hw = find_orca()
say("hwnd:", hw)


def sweep(tag):
    """逐个 index 渲染并存图，返回 {idx: (图像, 位姿)}"""
    out = {}
    for idx in range(7):
        try:
            call_text(m, "set_viewport_camera", {"camera_index": idx})
        except Exception as e:
            say("  idx%d set err %s" % (idx, str(e)[:70]))
        time.sleep(1.3)
        try:
            t = json.loads(call_text(m, "get_viewport_transform", {}))
            tr = t.get("transform", t)
        except Exception:
            tr = {}
        try:
            im = gl_crop(grab(hw))
            p = os.path.join(OUT, "%s_idx%d.png" % (tag, idx))
            im.save(p)
            out[idx] = (im, tr)
            say("  %s idx%d  %s  pos=%s scale=%s" % (
                tag, idx, "%dx%d" % im.size,
                [round(x, 2) for x in tr.get("position", [])], tr.get("scale")))
        except Exception as e:
            say("  %s idx%d grab err %s" % (tag, idx, e))
    return out


# ---------------------------------------------------------------- 原始位姿
orig = {}
d = json.loads(call_text(m, "get_all_actors", {}))
for a in STATIC:
    v = d.get(a) or {}
    orig[a] = (v.get("transform.position"), v.get("transform.rotation"))
    say("原始位姿 %-18s pos=%s rot=%s" % (a, orig[a][0], orig[a][1]))

say("\n=== 第一轮：原始状态 ===")
base = sweep("base")

# ---------------------------------------------------------------- 搬走
say("\n=== 把三台静置相机搬到高空 ===")
for a, (p, r) in MOVED.items():
    try:
        call_text(m, "set_actor_transform",
                  {"actor_path": a, "position": p, "rotation": r})
        say("  moved", a, "->", p)
    except Exception as e:
        say("  move err", a, str(e)[:90])
time.sleep(1.0)

say("\n=== 第二轮：静置相机已搬走 ===")
moved = sweep("moved")

# ---------------------------------------------------------------- 还原
say("\n=== 还原静置相机 ===")
for a, (p, r) in orig.items():
    try:
        call_text(m, "set_actor_transform",
                  {"actor_path": a, "position": p, "rotation": r})
    except Exception as e:
        say("  restore err", a, str(e)[:90])
time.sleep(0.6)
d2 = json.loads(call_text(m, "get_all_actors", {}))
for a in STATIC:
    v = d2.get(a) or {}
    say("  还原后 %-18s pos=%s" % (a, v.get("transform.position")))

try:
    call_text(m, "set_viewport_camera", {"camera_index": 0})
except Exception:
    pass

# ---------------------------------------------------------------- 比对
res = {}
for idx in base:
    if idx not in moved:
        continue
    a = crop(base[idx][0])
    b = crop(moved[idx][0])
    diff = float(np.abs(a - b).mean())
    res[idx] = {"diff": diff,
                "base_pos": base[idx][1].get("position"),
                "moved_pos": moved[idx][1].get("position"),
                "base_scale": base[idx][1].get("scale")}
    say("idx%d  前后差异 %6.2f   base_pos=%s  scale=%s   -> %s" % (
        idx, diff,
        [round(x, 2) for x in (res[idx]["base_pos"] or [])], res[idx]["base_scale"],
        "静置相机（画面随场景相机移动而变）" if diff > 4 else "不受场景相机影响（机载/自由相机）"))

with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
say("DONE", OUT)
