# -*- coding: utf-8 -*-
import os, sys, io
HERE = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect"
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import orca_boot  # noqa
import numpy as np
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr="localhost:50051",
                      agent_names=["pose"], time_step=0.001, render_mode="force")
env.initialize_grpc(); env.initialize_simulation()
m = env.model
names = [m.body(i).name for i in range(m.nbody)]
P = "dual_arm_collaborative_service_robot_1_"
want = [w for w in [P+"camera_head_body2", P+"camera_left_body2", P+"camera_right_body2",
                    P+"camera_head_body1", P+"camera_left_body1", P+"camera_right_body1"] if w in names]
print("found:", want)
res = env.get_body_xpos_xmat_xquat(want)
pos = np.asarray(res[0]).reshape(-1,3)
xmat = np.asarray(res[1]).reshape(-1,9)
for k,v,xm in zip(want,pos,xmat):
    R = xm.reshape(3,3)
    # camera looks along -Z of its frame (O3DE/OpenGL). print the -Z axis direction
    fwd = -R[:,2]
    print("%-52s pos=%s  forward(-Z)=%s" % (k.replace(P,''), np.round(v,3), np.round(fwd,3)))
env.close()