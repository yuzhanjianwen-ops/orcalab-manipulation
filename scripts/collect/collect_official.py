# -*- coding: utf-8 -*-
u"""键盘遥操作 + 采集 —— 相机走**官方流程**（env.start_streaming）。

与 collect.py 的唯一区别：相机接入方式。

    collect.py            : 自己 new CameraRecorder(name, 写死的端口) -> .start()
    collect_official.py   : env.start_streaming(name)  -> manager.get_recorder(...)

为什么改用官方流程
==================
官方流程多做两件我们之前没做的事（见 official_camera.py 顶部注释）：

  1. ``set_streaming_enabled(True)`` —— 真正打开引擎侧推流。
     之前只连端口，推流没开时「连得上、收不到帧」。
  2. 端口由后端相机属性给出，不再写死 7070/7080/7090。

其余（遥操作、按键、镜像、LeRobot 落盘、时间戳目录）全部复用 collect.py，
不复制一份代码 —— 免得以后改一处漏一处。

用法（只要键盘）
----------------
    python collect_official.py ^
        --lerobot-out D:\\data\\lerobot\\pick_medbox --task "pick the medbox"

（本脚本默认就用键盘，不必加 --keyboard）

按键
----
    I  开始 / 结束录制          J  保存（十字左）      L  丢弃（十字右）
    K  待命 / 中止              N  全场景复位           M  双臂镜像
    A / B  闭爪 / 开爪          X  换臂                 Y  回 home
    START 重同步                WASD/RF 平移升降        方向键 姿态
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import orca_boot                                          # noqa: F401,E402

import collect as C                                       # noqa: E402
from collect import State                                 # noqa: E402


class OfficialCamTeleop(C.CollectTeleop):
    u"""把 CollectTeleop 的相机换成官方流程，别的完全不动。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)

    # ------------------------------------------------------------ 相机接入
    def _open_official_cameras(self) -> bool:
        u"""用 env.start_streaming() 接三相机（官方流程）。"""
        from official_camera import OfficialCameraFeed

        self.cam = OfficialCameraFeed()
        # 先推一步仿真，让引擎开始推流（首帧要等 render 驱动）
        try:
            self._drive_sim(self.r.ctrl())
        except Exception as e:                              # noqa: BLE001
            print("[official-cam] 预推仿真失败（继续）: %s: %s"
                  % (type(e).__name__, e), flush=True)

        # ★ 关键：把 env 交给 feed —— 官方接口都在 env 上
        if not self.cam.open(self.r.u):
            print("[official-cam] 接不上：%s" % self.cam.error, flush=True)
            print("[warn] 继续以无图像模式采集", flush=True)
            return False

        self.cam3 = self.cam
        self.rec.set_images_fn(self._grab3_dict)
        st = self.cam.stats()
        print("[official-cam] 三相机已接入（env.start_streaming 官方流程）",
              flush=True)
        for tag in self.cam.channels:
            d = st["cameras"].get(tag, {})
            print("   %-6s %-14s port=%s" % (tag, d.get("camera"),
                                             d.get("port")), flush=True)
        print("[official-cam] 落盘字段: " + ", ".join(
            "image_%s" % t for t in self.cam.channels), flush=True)
        return True

    def run(self) -> None:
        # 主循环开始前接管相机（此时 r 已就绪）
        self._open_official_cameras()
        super().run()


# =================================================================== CLI
def main() -> int:
    ap = argparse.ArgumentParser(
        description=u"键盘遥操作 + 采集（相机走 OrcaGym 官方 start_streaming 流程）")
    ap.add_argument("--lerobot-out", default=None, metavar="DIR",
                    help=u"存成 LeRobot v3.0 数据集的目录（推荐）")
    ap.add_argument("--task", default="teleop", help=u"任务名，写入 meta")
    ap.add_argument("--lerobot-fps", type=int, default=20,
                    help=u"写进 LeRobot meta 的采集帧率（默认 20）")
    ap.add_argument("--lerobot-resume", action="store_true",
                    help=u"追加到已有 LeRobot 数据集")
    ap.add_argument("--no-lerobot-stamp", dest="lerobot_stamp",
                    action="store_false", default=True,
                    help=u"关掉时间戳子目录")
    ap.add_argument("--lerobot-no-videos", action="store_true",
                    help=u"用 parquet 内嵌 PNG 而非 mp4")
    ap.add_argument("--dataset", default=os.path.join(HERE, "dataset"),
                    help=u"不指定 --lerobot-out 时的 HDF5 目录")
    # 遥操作
    ap.add_argument("--keyboard", action="store_true", default=True,
                    help=u"用键盘（本脚本默认开）")
    ap.add_argument("--reset-key", default=None, help=u"复位键名，默认 N")
    ap.add_argument("--no-reset-in-rec", action="store_true",
                    help=u"禁止录制中复位")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--env-index", type=int, default=None)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--addr", default=None)
    ap.add_argument("--index", type=int, default=0)
    args = ap.parse_args()

    if not args.lerobot_out:
        print("[warn] 未指定 --lerobot-out，将退回 HDF5 格式", flush=True)

    lerobot_out = args.lerobot_out
    if lerobot_out and args.lerobot_stamp:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.abspath(lerobot_out)
        cand = os.path.join(base, stamp)
        n = 2
        while os.path.exists(cand):
            cand = os.path.join(base, "%s_%d" % (stamp, n))
            n += 1
        lerobot_out = cand
        print("[lerobot] 本次数据 -> %s" % lerobot_out, flush=True)

    reset_key = args.reset_key or "N"

    OfficialCamTeleop(
        dataset=args.dataset,
        task=args.task,
        cam3=False,                 # 不用视口渲染那路
        cam3_ws=False,              # 不用自己连端口的旧方式
        no_camera=True,             # 相机由本脚本的 _open_official_cameras() 接管，
                                    # 别让基类再默认开一遍机载三相机
        lerobot_out=lerobot_out,
        lerobot_fps=args.lerobot_fps,
        lerobot_resume=args.lerobot_resume,
        lerobot_videos=not args.lerobot_no_videos,
        camera_port=None,
        camera_grpc=True,
        include_rotation_6d=False,
        reset_key=reset_key,
        reset_in_recording=not args.no_reset_in_rec,
        render=not args.no_render,
        pad_index=args.index,
        keyboard=True,              # ★ 只要键盘
        env_index=args.env_index,
        agent=args.agent,
        addr=args.addr,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
