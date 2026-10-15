# -*- coding: utf-8 -*-
"""补跑：官方流程取三相机首帧 + 实测 vertical_fov 能不能改（90 -> 60 -> 还原）。

用法（OrcaStudio 已打开场景、仿真处于外部控制模式）：
    python _fov_probe.py

产出： _fov_probe/{fov90,fov60}_{head,left,right}.png + report.json
"""
import os, sys, io, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import orca_boot  # noqa: F401
import numpy as np
import grpc
from orca_gym.protos import mjc_message_pb2 as pb, mjc_message_pb2_grpc as pbg
from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv
from official_camera import OfficialCameraFeed

ADDR = "localhost:50051"
OUT = os.path.join(HERE, "_fov_probe")
os.makedirs(OUT, exist_ok=True)
CAMS = ["camera_head", "camera_left", "camera_right"]


def save(prefix, frames):
    from PIL import Image
    got = {}
    for k, v in frames.items():
        if v is None:
            got[k] = None
            continue
        fp = os.path.join(OUT, "%s_%s.png" % (prefix, k))
        Image.fromarray(v).save(fp)
        got[k] = {"shape": list(v.shape), "mean": round(float(v.mean()), 2),
                  "std": round(float(v.std()), 2), "path": fp}
        print("  saved %-26s %sx%s mean=%.1f std=%.1f" % (
            os.path.basename(fp), v.shape[1], v.shape[0], v.mean(), v.std()), flush=True)
    return got


def read_props(stub, name):
    return stub.GetCameraProperties(pb.GetCameraPropertiesRequest(camera_name=name), timeout=10)


print("== 1) 连接 ORCA 引擎 %s ==" % ADDR, flush=True)
env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr=ADDR,
                      agent_names=["fovprobe"], time_step=0.001,
                      render_mode="force")
env.initialize_grpc()
env.initialize_simulation()
env.set_sync_render(False)
env.set_render_fps(30)
print("  model nq=%s nv=%s nu=%s" % (env.model.nq, env.model.nv, env.model.nu), flush=True)
print("  registered cameras:", list(env.get_camera_names()), flush=True)

stub = pbg.GrpcServiceStub(grpc.insecure_channel(ADDR))

print("== 2) 基线相机属性（未开推流）==", flush=True)
baseline = {}
for n in CAMS:
    r = read_props(stub, n)
    baseline[n] = dict(streaming=r.streaming_enabled, rgb=r.capture_rgb,
                       fov=r.vertical_fov, w=r.width, h=r.height,
                       near=r.near_clip, far=r.far_clip, port=r.color_port)
    print("  %-13s streaming=%s rgb=%s fov=%s %sx%s near=%s far=%s port=%s" % (
        n, r.streaming_enabled, r.capture_rgb, r.vertical_fov, r.width, r.height,
        round(r.near_clip, 3), r.far_clip, r.color_port), flush=True)

print("== 3) 打开三路推流（capture_rgb=True）==", flush=True)
feed = OfficialCameraFeed(first_frame_timeout=20.0)
ok = feed.open(env)
print("  feed.open ->", ok, "|", feed.error, flush=True)
print("  channels:", feed.channels, flush=True)

idx = [-1]


def drive(n=20):
    ctrl = np.zeros(env.model.nu, dtype=np.float32)
    env.do_simulation(ctrl, n)
    idx[0] += 1
    env.render(simulate_index=idx[0], request_idr=(idx[0] == 0))


def pump(seconds=3.0, fps=30):
    t_end = time.time() + seconds
    dt = 1.0 / fps
    while time.time() < t_end:
        drive()
        feed._tick()
        time.sleep(dt)
    time.sleep(0.4)
    feed._tick()


pump(2.0)
f0 = feed.grab_multi()
print("  首帧:", {k: (None if v is None else v.shape) for k, v in f0.items()}, flush=True)

print("== 4) 抓 fov=90 基线图 ==", flush=True)
pump(3.0)
saved90 = save("fov90", feed.grab_multi())

print("== 5) 尝试 SetCameraProperties(vertical_fov=60) ==", flush=True)
for n in CAMS:
    try:
        stub.SetStreamingEnabled(pb.SetStreamingEnabledRequest(camera_name=n, enabled=False), timeout=10)
    except Exception as e:
        print("  [%s] stop stream rpc err: %s" % (n, e), flush=True)
    try:
        prop = pb.CameraProperty()
        prop.vertical_fov = 60.0
        resp = stub.SetCameraProperties(pb.SetCameraPropertiesRequest(camera_name=n, property=prop), timeout=10)
        print("  [%s] SetCameraProperties status=%s err=%r" % (n, resp.status, resp.error_message), flush=True)
    except Exception as e:
        print("  [%s] SetCameraProperties EXC %s: %s" % (n, type(e).__name__, e), flush=True)

print("  改后回读：", flush=True)
changed = {}
for n in CAMS:
    r = read_props(stub, n)
    changed[n] = r.vertical_fov
    print("    %-13s fov=%s streaming=%s" % (n, r.vertical_fov, r.streaming_enabled), flush=True)

fov_changed = all(abs(changed[n] - 60.0) < 0.5 for n in CAMS)
print("== 6) FOV 是否真改到 60: %s ==" % fov_changed, flush=True)
saved60 = {}
if fov_changed:
    for n in CAMS:
        try:
            env.start_streaming(n, capture_rgb=True)
        except Exception as e:
            print("  restart %s err %s" % (n, e), flush=True)
    feed.close()
    feed = OfficialCameraFeed(first_frame_timeout=20.0)
    print("  reopen feed ->", feed.open(env), feed.error, flush=True)
    pump(3.0)
    saved60 = save("fov60", feed.grab_multi())

print("== 7) 还原 vertical_fov=90 ==", flush=True)
for n in CAMS:
    try:
        stub.SetStreamingEnabled(pb.SetStreamingEnabledRequest(camera_name=n, enabled=False), timeout=10)
        prop = pb.CameraProperty()
        prop.vertical_fov = 90.0
        resp = stub.SetCameraProperties(pb.SetCameraPropertiesRequest(camera_name=n, property=prop), timeout=10)
        print("  [%s] restore status=%s err=%r" % (n, resp.status, resp.error_message), flush=True)
    except Exception as e:
        print("  [%s] restore EXC %s: %s" % (n, type(e).__name__, e), flush=True)

final = {}
for n in CAMS:
    r = read_props(stub, n)
    final[n] = r.vertical_fov
    print("    %-13s fov=%s streaming=%s" % (n, r.vertical_fov, r.streaming_enabled), flush=True)

report = {"baseline": baseline, "after_set_60": changed,
          "fov_changed_to_60": fov_changed, "restored": final,
          "saved_fov90": saved90, "saved_fov60": saved60}
with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("== 报告已写 %s ==" % os.path.join(OUT, "report.json"), flush=True)

try:
    feed.close()
except Exception:
    pass
try:
    env.close()
except Exception:
    pass
print("DONE", flush=True)