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
jn = m.get_joint_names() if hasattr(m, "get_joint_names") else None
print("njoints:", len(jn) if jn else "?")
for i, n in enumerate(jn or []):
    print("  %2d %s" % (i, n))
print("nu=", m.nu if hasattr(m,"nu") else "?")
env.close()