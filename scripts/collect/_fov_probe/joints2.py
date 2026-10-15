# -*- coding: utf-8 -*-
import os, sys, io
sys.path.insert(0, r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import orca_boot  # noqa
import numpy as np
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["j"], time_step=0.001, render_mode="force")
env.initialize_grpc(); env.initialize_simulation()
m = env.model
print("model attrs:", [a for a in dir(m) if 'name' in a.lower() or 'joint' in a.lower()][:40])
try:
    print("joint_names:", m.joint_names if hasattr(m,'joint_names') else m.get_joint_names())
except Exception as e:
    print("jn err", e)
# try actuator names
for attr in ["actuator_names","get_actuator_names","ctrl_names"]:
    if hasattr(m, attr):
        v = getattr(m, attr)
        v = v() if callable(v) else v
        print(attr, "->", list(v)[:45])
env.close()