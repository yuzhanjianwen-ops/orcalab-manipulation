# -*- coding: utf-8 -*-
"""同屏对比：真实 OrcaStudio 编辑器窗口 vs 采集用的两条渲染链路。

产出目录： _fov_probe/now/
  real_window_*.png    真实的 OrcaStudio 窗口截图（这次按进程名+标题定位，避免抓错）
  agent_idx{i}.png     MCP get_viewport_png(index=i) 渲染（AgentCamera 离屏）
  报告直接打印到 stdout
"""
import os, sys, io, json, time, ctypes
from ctypes import wintypes
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PIL import Image, ImageGrab
try:
    import psutil
except Exception:
    psutil = None

OUT = os.path.join(HERE, "_fov_probe", "now")
os.makedirs(OUT, exist_ok=True)

u = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
res = []


def _cb(h, l):
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if not u.IsWindowVisible(h):
        return True
    n = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, n, 512)
    if not n.value.strip():
        return True
    pname, ppath = "?", ""
    if psutil:
        try:
            p = psutil.Process(pid.value)
            pname, ppath = p.name(), (p.exe() or "")
        except Exception:
            pass
    res.append((h, pid.value, pname, ppath, n.value))
    return True


u.EnumWindows(CB(_cb), None)

print("=== 所有可见顶层窗口 ===")
orca_wins = []
for h, pid, pname, ppath, title in res:
    is_orca = ("orca" in pname.lower()) or ("orcalab" in ppath.lower()) or ("26." in title)
    print("  hwnd=%-9d pid=%-6d %-20s %-40s %r%s" % (
        h, pid, pname, os.path.basename(ppath)[:38], title[:60], "   <== ORCA" if is_orca else ""))
    if is_orca:
        orca_wins.append((h, pid, pname, title))

print("=== 抓取 OrcaStudio 窗口 ===")
for h, pid, pname, title in orca_wins:
    try:
        u.ShowWindow(h, 9)          # SW_RESTORE
        u.SetForegroundWindow(h)
        time.sleep(0.8)
    except Exception:
        pass
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    w, ht = r.right - r.left, r.bottom - r.top
    try:
        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
        fp = os.path.join(OUT, "real_window_%d.png" % h)
        img.save(fp)
        print("  saved %s  %dx%d  title=%r" % (os.path.basename(fp), img.size[0], img.size[1], title[:50]))
    except Exception as e:
        print("  grab %d err %s" % (h, e))

# ---------------- MCP ----------------
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp()
print("=== MCP ===")
print("serverInfo:", m.connect())
ts = {t["name"]: t for t in m.tools()}
vp_tools = [n for n in ts if "viewport" in n.lower() or "camera" in n.lower() or "png" in n.lower()]
print("viewport/camera 相关工具:", vp_tools)
print("state:", call_text(m, "get_simulation_state", {}))

info_raw = call_text(m, "get_viewport_camera_info", {})
print("当前 viewport 信息:", info_raw[:600])
try:
    info = json.loads(info_raw)
    print("  transform:", json.dumps(info.get("transform"), ensure_ascii=False))
    print("  color_path:", info.get("color_path"))
except Exception:
    pass

print("=== 逐个 index 渲染（get_viewport_png）===")
for i in range(6):
    try:
        r = call_text(m, "get_viewport_png", {"index": i})
        print("  idx%d -> %s" % (i, r[:120]))
    except Exception as e:
        print("  idx%d ERR %s" % (i, str(e)[:120]))
    time.sleep(0.4)
    # 渲染结果落到 AgentCamera png
    for cand in [os.path.expanduser("~/.orcalab/viewport_image/color/AgentCamera_color_0.png"),
                 os.path.expanduser("~/.orcalab/viewport_color_%d.png") % i]:
        if os.path.exists(cand):
            try:
                im = Image.open(cand)
                im.save(os.path.join(OUT, "agent_idx%d.png" % i))
                print("     copied %s %s" % (os.path.basename(cand), im.size))
                break
            except Exception:
                pass

# 当前显示相机位姿（切回 0 之前先读一遍）
for i in range(6):
    try:
        call_text(m, "set_viewport_camera", {"camera_index": i})
        time.sleep(0.3)
        t = json.loads(call_text(m, "get_viewport_transform", {}))
        tr = t.get("transform", t)
        print("  idx%d pos=%s rot=%s scale=%s" % (
            i, [round(x, 3) for x in tr.get("position", [])],
            [round(x, 1) for x in tr.get("rotation", [])], tr.get("scale")))
    except Exception as e:
        print("  idx%d pose err %s" % (i, str(e)[:100]))

print("DONE")
