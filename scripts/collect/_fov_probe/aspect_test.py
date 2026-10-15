# -*- coding: utf-8 -*-
import os, io, sys
import numpy as np
from PIL import Image
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe"
vp = Image.open(os.path.join(D, "viewport_cams", "cam1.png")).convert("RGB")  # head viewport, 1080x1080
st = Image.open(os.path.join(D, "stream_head.png")).convert("RGB")            # 640x480
vpa = np.asarray(vp, dtype=np.float32); sta = np.asarray(st, dtype=np.float32)

# 模型A: 竖直FOV都是90 -> 竖直内容一一对应
#   viewport(1080x1080, hfov=90)  vs  stream(640x480, hfov=106.26)
#   把 stream 横向量程压缩到 viewport 的 84.7% 再比
vp_small = np.asarray(vp.resize((480, 480), Image.LANCZOS), dtype=np.float32)
st_c = sta[:, 51:589, :]
st_c = np.asarray(Image.fromarray(st_c.astype(np.uint8)).resize((480, 480), Image.LANCZOS), dtype=np.float32)
print("center-crop model  mean|diff| = %.1f" % np.abs(vp_small - st_c).mean())

# 对照：不做横向补偿，直接整幅缩放
st_full = np.asarray(st.resize((480, 480), Image.LANCZOS), dtype=np.float32)
print("plain-resize model mean|diff| = %.1f" % np.abs(vp_small - st_full).mean())

# 数值：视角与像素密度
import math
vfov = 90.0
def hfov(w, h, vfov):
    return 2*math.degrees(math.atan((w/h)*math.tan(math.radians(vfov/2))))
print("viewport 1080x1080: hfov=%.1f deg, px/deg=%.2f" % (hfov(1080,1080,vfov), 1080/hfov(1080,1080,vfov)))
print("stream   640x480 : hfov=%.1f deg, px/deg=%.2f" % (hfov(640,480,vfov), 640/hfov(640,480,vfov)))