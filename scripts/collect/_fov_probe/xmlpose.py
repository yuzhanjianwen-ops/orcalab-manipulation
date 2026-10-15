# -*- coding: utf-8 -*-
import sys, os, re, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# out.xml 位于 OrcaStudio 工程目录的 tmp/ 下：
#   %LOCALAPPDATA%\Orca\OrcaStudio\<工程GUID>\tmp\out.xml
# 「工程 GUID」每台机器不同，因此动态查找；也可用 ORCA_ORCASTUDIO_TMP 直接指定该 tmp 目录。
_root = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
                     "Orca", "OrcaStudio")
_env = os.environ.get("ORCA_ORCASTUDIO_TMP")
if _env:
    p = os.path.join(_env, "out.xml")
else:
    p = next((os.path.join(_root, g, "tmp", "out.xml")
              for g in (sorted(os.listdir(_root)) if os.path.isdir(_root) else [])
              if os.path.exists(os.path.join(_root, g, "tmp", "out.xml"))), None)
if not p or not os.path.exists(p):
    sys.exit("找不到 out.xml。请设置环境变量 ORCA_ORCASTUDIO_TMP="
             "<OrcaStudio 工程目录下的 tmp 路径>")
s = open(p, "rb").read().decode("utf-8", "replace")
for tag in ["camera_head_body1","camera_head_body2","camera_left_body1","camera_left_body2","camera_right_body1","camera_right_body2"]:
    key = 'name="dual_arm_collaborative_service_robot_1_%s"' % tag
    i = s.find(key)
    if i < 0:
        print(tag, "NOT FOUND"); continue
    j = s.rfind("<body", 0, i)
    frag = s[j:i+len(key)+3]
    mp = re.search(r'pos="([^"]*)"', frag); me = re.search(r'euler="([^"]*)"', frag)
    print("%-22s pos=%s euler=%s" % (tag, mp.group(1) if mp else "?", me.group(1) if me else "?"))