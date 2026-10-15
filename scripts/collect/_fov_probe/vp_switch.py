# -*- coding: utf-8 -*-
import os, sys, io, json, time, shutil
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
from PIL import Image
OUT = os.path.join(HERE, "_fov_probe", "viewport_cams")
os.makedirs(OUT, exist_ok=True)
m = OrcaMcp(); m.connect()
src = os.path.expanduser("~/.orcalab/viewport_image/color/AgentCamera_color_0.png")
for idx in range(6):
    try:
        r = call_text(m, "set_viewport_camera", {"camera_index": idx})
    except Exception as e:
        print(idx, "set err", e); continue
    time.sleep(0.6)
    try:
        info = json.loads(call_text(m, "get_viewport_camera_info"))
    except Exception as e:
        info = {"err": str(e)}
    try:
        call_text(m, "get_viewport_png", {"index": idx})
    except Exception:
        pass
    time.sleep(0.5)
    dst = os.path.join(OUT, "cam%d.png" % idx)
    try:
        shutil.copy(src, dst)
        im = Image.open(dst)
        print("idx %d -> %s  %s  transform=%s" % (idx, os.path.basename(dst), im.size, info.get("transform")))
    except Exception as e:
        print("idx %d copy err %s  info=%s" % (idx, e, info))