# -*- coding: utf-8 -*-
"""演示：把 OrcaStudio 主视口逐个切到 0..5 号相机，抓该相机真正看到的画面。

等价于「在软件『相机』面板里点某一台相机」——点击动作最终调用的就是
CameraRequestBus.set_viewport_camera(index)，与这里的 set_viewport_camera 同一条路径。

产出自 _fov_probe/vpcam/；结束前把视口还原到起始 index。
"""
import os, sys, io, json, time, shutil
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
from PIL import Image

OUT = os.path.join(HERE, "_fov_probe", "vpcam")
os.makedirs(OUT, exist_ok=True)
SRC = os.path.expanduser("~/.orcalab/viewport_image/color/AgentCamera_color_0.png")

m = OrcaMcp()
m.connect()

# 记录起始位姿，便于还原
start = json.loads(call_text(m, "get_viewport_camera_info"))["transform"]
print("起始视口位姿:", [round(x, 3) for x in start["position"]])
print("仿真状态:", call_text(m, "get_simulation_state", {})[:160])
print()

rows = []
start_idx = None
for i in range(6):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": i})
        time.sleep(0.9)
        t = json.loads(call_text(m, "get_viewport_transform", {}))["transform"]
        pos = [round(x, 3) for x in t.get("position", [])]
        sc = t.get("scale", -1)
        if abs(t["position"][0] - start["position"][0]) < 1e-6 and abs(t["position"][1] - start["position"][1]) < 1e-6:
            start_idx = i
        call_text(m, "get_viewport_png", {"index": i})
        time.sleep(0.8)
        dst = os.path.join(OUT, "vp_%d.png" % i)
        shutil.copy(SRC, dst)
        im = Image.open(dst)
        kind = "机载镜头" if abs(sc - 1.695) < 0.01 else ("自由相机" if abs(sc - 1.0) < 0.01 else "?")
        # 与机载相机位姿对照
        guess = ""
        if abs(sc - 1.695) < 0.01:
            gp = (round(t["position"][0], 2), round(t["position"][1], 2))
            table = {(18.06, -3.38): "≈ camera_head（头部）",
                     (18.24, -4.69): "≈ camera_right（右腕）",
                     (18.22, -2.06): "≈ camera_left（左腕）"}
            guess = table.get(gp, "机载（其它）")
        print("idx %d  scale=%.3f  %-8s pos=%s  %s  -> %s %s" % (i, sc, kind, pos, guess, os.path.basename(dst), im.size))
        rows.append((i, sc, pos, dst, guess))
    except Exception as e:
        print("idx %d err %s" % (i, str(e)[:90]))

# 还原
if start_idx is not None:
    call_text(m, "set_viewport_camera", {"camera_index": start_idx})
    print("\n视口已还原到 idx %d" % start_idx)

# 拼图
try:
    from PIL import ImageDraw
    TH = 320
    def fit(im, th=TH):
        w, h = im.size
        return im.resize((int(w * th / h), th), Image.LANCZOS)
    tiles = []
    for i, sc, pos, p, guess in rows:
        tiles.append((("idx%d  scale=%.3f  %s" % (i, sc, guess or "自由")), fit(Image.open(p).convert("RGB"))))
    gap, lab = 8, 20
    cols = 3
    rr = (len(tiles) + cols - 1) // cols
    W = cols * tiles[0][1].width + gap * (cols + 1)
    H = rr * (TH + lab) + gap * (rr + 1) + 22
    M = Image.new("RGB", (W, H), (18, 18, 18))
    d = ImageDraw.Draw(M)
    d.text((gap, 5), "OrcaStudio viewport cameras 0..5 - what each one actually sees", fill=(255, 220, 0))
    for k, (lbl, im) in enumerate(tiles):
        c, r = k % cols, k // cols
        x = gap + c * (im.width + gap)
        y = 22 + gap + r * (TH + lab)
        d.text((x + 2, y), lbl, fill=(0, 255, 128))
        M.paste(im, (x, y + lab))
    o = os.path.join(OUT, "viewport_cams_what_you_see.png")
    M.save(o)
    print("拼图:", o, M.size)
except Exception as e:
    print("montage err", e)
