# -*- coding: utf-8 -*-
import os, sys, io, json, time
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import orca_boot  # noqa
import numpy as np
from PIL import Image, ImageDraw
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
from orca_mcp import OrcaMcp, call_text

OUT = os.path.join(HERE, "_fov_probe")
m = OrcaMcp(); m.connect()

# 机器人三相机实体属性（软件里的值）
P = "/dual_arm_collaborative_service_robot_1"
for ent in ["camera_head", "camera_left", "camera_right"]:
    for path in ["%s/%s_body2/cameras/%s" % (P, ent, ent), "%s/%s" % (P, ent)]:
        try:
            r = call_text(m, "get_actor_properties", {"actor_name": path})
            print("=" * 20, path)
            print(r[:1200])
            break
        except Exception as e:
            pass