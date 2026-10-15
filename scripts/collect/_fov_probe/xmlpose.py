# -*- coding: utf-8 -*-
import sys, os, re, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
p = r"C:\Users\86322\AppData\Local\Orca\OrcaStudio\{3DB8A56E-2458-4543-93A1-1A41756B97DA}\tmp\out.xml"
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