# -*- coding: utf-8 -*-
"""端到端自测：不用键盘，直接驱动采集状态机，
验证 「三相机(WS) + LeRobot 直存」 整条链路。

流程：
    建 CollectTeleop（--cam3-ws 等价）-> arm() -> 录 N 帧 -> save() -> close()

用法：
    python e2e_test.py --out D:\\...\\lerobot_e2e --frames 60
"""
from __future__ import annotations
import argparse, os, sys, time, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "_camera_tmp")) if False else None

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    if os.path.isdir(out):
        if not args.keep:
            shutil.rmtree(out, ignore_errors=True)
            print("[e2e] 清掉旧目录", out)
        else:
            print("[e2e] --keep，保留已有目录", out)

    from collect import CollectTeleop
    from recorder import State

    print("[e2e] 构造 CollectTeleop (cam3_ws=True, lerobot_out=%s)" % out)
    t = CollectTeleop(
        dataset=os.path.join(HERE, "dataset"),
        task="e2e_pick",
        cam3_ws=True,
        camera_port=None,
        lerobot_out=out,
        lerobot_fps=args.fps,
        lerobot_videos=True,
        keyboard=True,          # 键盘驱动（不真的按键，我们直接调状态机）
        render=True,
        reset_in_recording=True,
    )
    print("[e2e] cam3 ws ok=%s channels=%s" % (bool(t.cam3), getattr(t.cam, "channels", None)))

    # 直接调状态机：arm -> start -> 录 N 帧 -> stop -> save
    print("[e2e] arm()")
    print("   ->", t.rec.arm())
    print("[e2e] toggle_record() -> RECORDING")
    print("   ->", t.rec.toggle_record())
    assert t.rec.state is State.RECORDING, t.rec.state

    dt = t.r.dt
    side = t.active
    sim = -1
    img_ok = 0
    for i in range(args.frames):
        t0 = time.perf_counter()
        # 下发（不动物体，仅保持姿态，重点是把相机流走起来）
        t.osc[side].set_goal(t.goal[side][0], t.goal[side][1])
        c = t.r.ctrl()
        for s in ("l", "r"):
            c = t._apply_osc(c, t.osc[s])
        c = t._apply_grip(c)

        t._drive_sim(c)

        action = {"goal_pos": t.goal[side][0], "goal_mat": t.goal[side][1],
                  "gripper_cmd": t.grip_cmd[side]}
        fd = t.grabber(action)
        fd["n_resets"] = np.float32(0)
        t.rec.capture(fd)
        imgs = t._grab3_dict()
        if all(v is not None for v in imgs.values()):
            img_ok += 1

        slack = dt - (time.perf_counter() - t0)
        if slack > 0:
            time.sleep(slack)
        if (i + 1) % 20 == 0:
            print("  %d/%d  三路齐=%d  帧数=%d"
                  % (i + 1, args.frames, img_ok, t.rec.episode.n_frames))

    print("[e2e] 停 + 保存")
    print("   ->", t.rec.toggle_record())
    assert t.rec.state is State.REVIEW
    msg = t.rec.save()
    print("[e2e] save ->", msg)

    t.cam.close()
    try:
        t.saver.close()
    except Exception as e:
        print("[e2e] saver.close 异常:", e)
    try:
        t.r.close()
    except Exception:
        pass

    # ---- 校验产物 ----
    print()
    print("[e2e] 目录树:")
    total = 0
    for root, dirs, files in os.walk(out):
        depth = root[len(out):].count(os.sep)
        if depth <= 3:
            print("  " * depth + os.path.basename(root) + "/")
        for f in files:
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            total += sz
            print("  " * (depth + 1) + "%-44s %8.2f KB" % (f, sz / 1024.0))
    print("[e2e] 总大小 %.2f MB" % (total / 1e6))

    # 用 lerobot 读回来
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds = LeRobotDataset(repo_id="local/e2e_pick", root=out, video_backend="pyav")
    print("[e2e] 读回: %d 帧" % len(ds))
    s = ds[0]
    for k in sorted(s):
        v = s[k]
        print("   %-32s %s %s" % (k, getattr(v, "shape", None), getattr(v, "dtype", None)))
    print("[e2e] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
