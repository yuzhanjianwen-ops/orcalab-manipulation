# -*- coding: utf-8 -*-
"""把已抓好的 vpmap/gl_idxN.png 重新拼一遍，这次每格标注"这是哪台相机"。

身份来源：
  scale=1.000            -> 自由相机（编辑器默认视口相机，不是机器人相机）
  scale=1.695(机器人缩放) -> 机载相机，再按位姿和场景相机 actor 对齐：
       /head_camera_1    (18.450,-3.350,2.150)
       /wrist_camera_l   (18.244,-4.691,1.922)
       /wrist_camera_r   (18.220,-2.057,1.871)
"""
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from PIL import Image, ImageDraw

V = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe\vpmap"
CAM_ACTORS = {
    "wrist_camera_l": (18.244, -4.691, 1.922),
    "wrist_camera_r": (18.220, -2.057, 1.871),
    "head_camera_1": (18.450, -3.350, 2.150),
}


def d2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def identify(scale, pos):
    if abs(scale - 1.0) < 0.01:
        return "自由相机（编辑器默认，不是机器人相机）", ""
    if abs(scale - 1.695) < 0.01:
        best, bd = None, 1e9
        for k, v in CAM_ACTORS.items():
            dd = d2(pos, v)
            if dd < bd:
                best, bd = k, dd
        if bd < 0.35:
            return "机载相机 %s" % best, "Δ%.3fm" % bd
        return "机载相机（机器人自带头相机 head_link2）", "无场景同名 actor，x 差 %.2f" % abs(pos[0] - 18.45)
    return "未知 scale=%.3f" % scale, ""


poses = json.load(open(os.path.join(V, "poses.json"), encoding="utf-8"))
TH, GAP, LAB = 300, 10, 40
tiles = []
for i in range(6):
    p = os.path.join(V, "gl_idx%d.png" % i)
    if not os.path.exists(p):
        continue
    t = poses.get(str(i), {})
    pos = t.get("position", [])
    who, extra = identify(t.get("scale", -1), pos)
    im = Image.open(p).convert("RGB")
    w, h = im.size
    tiles.append(((i, t.get("scale", -1), pos, who, extra),
                  im.resize((max(1, int(w * TH / h)), TH), Image.LANCZOS)))

cols = 3
rn = (len(tiles) + cols - 1) // cols
W = cols * tiles[0][1].width + GAP * (cols + 1)
H = 30 + rn * (TH + LAB) + GAP
M = Image.new("RGB", (W, H), (16, 16, 16))
d = ImageDraw.Draw(M)
d.text((GAP, 8), "OrcaStudio 主视口 index 0..5 —— 每一格到底是哪台相机", fill=(255, 220, 0))
for k, (info, im) in enumerate(tiles):
    i, sc, pos, who, extra = info
    c, r = k % cols, k // cols
    x = GAP + c * (im.width + GAP)
    y = 30 + r * (TH + LAB)
    d.text((x + 2, y), "idx%d  scale=%.3f" % (i, sc), fill=(0, 255, 128))
    d.text((x + 2, y + 14), who, fill=(255, 255, 255))
    d.text((x + 2, y + 26), "pos[%s] %s" % (",".join("%.2f" % v for v in pos), extra),
           fill=(150, 200, 255))
    M.paste(im, (x, y + LAB - 12))
o = os.path.join(V, "gl_indices_montage_labeled.png")
M.save(o)
print("saved", o, M.size)
for info, _ in tiles:
    i, sc, pos, who, extra = info
    print("  idx%d scale=%.3f %-46s pos=%s %s" % (i, sc, who, [round(v, 2) for v in pos], extra))
