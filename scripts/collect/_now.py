# -*- coding: utf-8 -*-
import os,sys,io,time
sys.path.insert(0,os.getcwd())
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8",errors="replace")
import orca_boot
import numpy as np, gymnasium as gym
from orca_gym.scripts.run_sim_loop import register_env
from official_camera import OfficialCameraFeed
from PIL import Image
OUT=r"D:\OTHERS\projects\orcalab-manipulation\_now"
os.makedirs(OUT,exist_ok=True)
AGENT="dual_arm_collaborative_service_robot_1"
env_id,_=register_env("localhost:50051","SimulationLoop",0,AGENT,sys.maxsize)
env=gym.make(env_id); u=env.unwrapped; u.reset()
P="dual_arm_collaborative_service_robot_1_"
sim=[0]
def drive():
    sim[0]+=1
    u.do_simulation(np.zeros(u.model.nu), u.frame_skip); u.render(simulate_index=sim[0], request_idr=(sim[0]==1))
feed=OfficialCameraFeed(first_frame_timeout=25.0)
print("open",feed.open(u),feed.error)
for _ in range(150): drive(); time.sleep(1/60)
time.sleep(0.4)
fr=feed.grab_multi()
for k,v in fr.items(): Image.fromarray(v).save(os.path.join(OUT,"%s.png"%k)); print(k,v.shape,"mean %.1f"%v.mean())
r=u.get_body_xpos_xmat_xquat([P+"camera_head_body2",P+"camera_left_body2",P+"camera_right_body2",
   P+"gripper_l_inner_link1",P+"gripper_r_inner_link1"])
p=np.asarray(r[0]).reshape(-1,3)
for n,v in zip(["cam_head","cam_left","cam_right","grip_l","grip_r"],p): print("  %-9s %s"%(n,np.round(v,3)))
env.close(); print("DONE")
