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
print("actuators (nu=%d):" % m.nu)
for i in range(m.nu):
    try: print("  %2d %s" % (i, m.actuator_id2name(i)))
    except Exception as e: print(i, e)
env.close()