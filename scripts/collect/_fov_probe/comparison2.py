# -*- coding: utf-8 -*-
"""对照：编辑器 GL 视口(窗口截图) vs MCP get_viewport_png(AgentCamera 离屏渲染)。"""
import os, sys, io, json, time, shutil, ctypes
from ctypes import wintypes
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from PIL import Image, ImageGrab
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe", "cmp2")
os.makedirs(OUT, exist_ok=True)
m = OrcaMcp(); m.connect()

# --- A) 编辑器窗口截图 ---
u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
hs = []
def cb(h, l):
    pid = ctypes.c_ulong(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value == 28268:
        n = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, n, 512)
        if u.IsWindowVisible(h) and "26." in n.value:
            hs.append(h)
    return True
u.EnumWindows(CB(cb), None)
print("window handles:", hs)
win_img = None
if hs:
    r = wintypes.RECT(); u.GetWindowRect(hs[0], ctypes.byref(r))
    win_img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
    print("A) 编辑器窗口截图 :", win_img.size, " (含菜单/层级联)")
    win_img.save(os.path.join(OUT, "A_editor_window.png"))
    # crop the central GL area approximately
    W, H = win_img.size
    crop = win_img.crop((int(W*0.24), int(H*0.13), int(W*0.865), int(H*0.96)))
    crop.save(os.path.join(OUT, "A_editor_glarea.png"))
    print("   GL 区域裁剪 :", crop.size)

# --- B) 当前 viewport 相机信息 ---
info = json.loads(call_text(m, "get_viewport_camera_info"))
print("B) MCP viewport 相机信息:")
print("   transform:", info["transform"])
print("   color_path:", info["color_path"])

# --- C) MCP 抓 viewport 图 ---
try:
    call_text(m, "get_viewport_png", {"index": 0})
except Exception as e:
    print("   render warning:", str(e)[:100])
time.sleep(1.0)
src = os.path.expanduser("~/.orcalab/viewport_image/color/AgentCamera_color_0.png")
dst = os.path.join(OUT, "B_mcp_viewport.png")
shutil.copy(src, dst)
im = Image.open(dst)
print("C) MCP get_viewport 图 :", im.size)

# --- D) 各视口相机索引的位姿 ---
print("D) 6 个视口相机(pos / rot / scale):")
for i in range(6):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": i})
        time.sleep(0.25)
        t = json.loads(call_text(m, "get_viewport_transform"))["transform"]
        print("   idx%d scale=%.3f pos=%s" % (i, t.get("scale",-1), [round(x,3) for x in t["position"]]))
    except Exception as e:
        print("   idx", i, "err", str(e)[:60])