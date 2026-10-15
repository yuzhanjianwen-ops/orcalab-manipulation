# -*- coding: utf-8 -*-
import os, sys, io, time
sys.path.insert(0, r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import orca_boot  # noqa
import numpy as np
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["probe"], time_step=0.001, render_mode="force")
env.initialize_grpc()
env.initialize_simulation()
print("registered cameras:", list(env.get_camera_names()))
m = env.model
names = [m.body(i).name for i in range(m.nbody)]
print("nbody=", m.nbody, " ncam=", m.ncam, " nsite=", m.nsite)
print("--- camera-ish bodies / sites ---")
for i in range(m.nbody):
    n = m.body(i).name
    if "camera" in n.lower():
        print("  BODY", n)
for i in range(m.nsite):
    n = m.site(i).name
    if "camera" in n.lower():
        print("  SITE", n)
P = "dual_arm_collaborative_service_robot_1_"
want = [P+"camera_head_body", P+"camera_head_body1", P+"camera_head_body2",
        P+"camera_left_body1", P+"camera_left_body2",
        P+"camera_right_body1", P+"camera_right_body2",
        P+"gripper_l_inner_link1", P+"gripper_r_inner_link1",
        P+"arm_l_end_link", P+"arm_r_end_link"]
avail = [w for w in want if w in names]
print("--- found camera bodies:", [w for w in avail if "camera" in w])
res = env.get_body_xpos_xmat_xquat(avail)
pos = np.asarray(res[0]).reshape(-1, 3)
q = np.asarray(res[2]).reshape(-1, 4) if len(res) > 2 else None
for k, v in zip(avail, pos):
    print("  %-58s %s" % (k, np.round(v, 3)))
env.close()