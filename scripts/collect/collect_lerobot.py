# -*- coding: utf-8 -*-
"""主采集脚本（LeRobot v3.0 版）：遥操作 + 按键状态机 + LeRobot 落盘。

与 ``collect.py`` 的关系
-----------------------
``collect.py``  : 遥操作 + 状态机 + **HDF5** 落盘
``collect_lerobot.py`` : 遥操作 + 状态机 + **LeRobot v3.0** 落盘  <- 本文件

两者**共用同一套**遥操作、状态机、按键、相机代码，**唯一区别是落盘器**：

    collect.py          ->  Recorder.set_saver(Hdf5Saver(...))
    collect_lerobot.py  ->  Recorder.set_saver(LeRobotSaver(...))

所以手感、按键、相机行为与 ``collect.py`` **完全一致**，
``collect.py`` 不受任何影响（两个文件并存，互不干扰）。

参考
----
落盘逻辑参考甲方 ``OrcaManipulation/src/dataStorage/lerobot_data_storage.py``
的 ``LeRobotDatasetWriter``（见 ``saver_lerobot.py`` 顶部注释的对照说明）。

用法
----
    # 键盘，输出到 ./lerobot_out/my_dataset
    python collect_lerobot.py --keyboard --flip-lr \
        --lerobot-out D:/data/lerobot/pick_medbox

    # 手柄
    python collect_lerobot.py --flip-lr \
        --lerobot-out D:/data/lerobot/pick_medbox

    # 追加到已有数据集（断点续采）
    python collect_lerobot.py --keyboard --flip-lr \
        --lerobot-out D:/data/lerobot/pick_medbox --resume

按键（与 collect.py 完全一致）
------------------------------
    十字下  待命 / 取消 / 中止      （键盘 K）
    十字上  开始 / 结束录制          （键盘 I）
    十字左  保存                     （键盘 J）
    十字右  丢弃                     （键盘 L）
    复位    RSTICK / N

依赖
----
    & "<你的python.exe>" -m pip install "lerobot[dataset]>=0.6.1" pyarrow
    注意 av 必须 <16。
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 复用 collect.py 里的所有非落盘逻辑（遥操作、状态机、按键、相机、主循环）
import collect as _c                                          # noqa: E402
from collect import CollectTeleop, banner                     # noqa: E402
from saver_lerobot import LeRobotSaver, lerobot_available     # noqa: E402


# =================================================================== 主类
class CollectTeleopLeRobot(CollectTeleop):
    """把 collect.py 的 HDF5 落盘器换成 LeRobot 落盘器。

    只做一件事：在 ``super().__init__`` 之后，把 ``rec`` 的 saver
    从 ``Hdf5Saver`` 换成 ``LeRobotSaver``。其余逻辑（遥操作、状态机、
    按键边沿检测、相机、复位）**全部继承自 collect.py**，因此行为一致。
    """

    def __init__(self, lerobot_out: str, repo_id: str = "local/manipulation",
                 fps: int = 20, task_desc: str = "teleop",
                 resume: bool = False, **kw):
        # 探活要放在最前：没有 lerobot 就立刻报错，不必先连仿真。
        ok, why = lerobot_available()
        if not ok:
            raise SystemExit(
                "\n无法启动 LeRobot 采集：\n" + why + "\n\n"
                "安装后重试；或改用 HDF5 采集（collect.py）。")

        # collect.py 的签名里已有 task= 参数，这里统一走它，避免重复传参
        kw.pop("task", None)
        super().__init__(dataset=lerobot_out, task=task_desc, **kw)

        # ---- 换成 LeRobot 落盘器 -------------------------------------
        self.lerobot_saver = LeRobotSaver(
            root=lerobot_out,
            repo_id=repo_id,
            fps=fps,
            robot_type="dual_arm_collaborative_service_robot_1",
            task=task_desc,
            cameras=None,          # 相机就绪后填 {cam: {height, width}}
            resume=resume,
        )
        self.rec.set_saver(self.lerobot_saver)
        # 原 Hdf5Saver 不再使用，但仍留着不碍事

        print()
        print("  ── 落盘格式：LeRobot v3.0 ───────────────────────────")
        print("  数据集根目录 : %s" % os.path.abspath(lerobot_out))
        print("  repo_id      : %s" % repo_id)
        print("  fps          : %d" % fps)
        print("  追加模式     : %s" % ("是" if resume else "否（覆盖）"))
        print("  结构          : data/*.parquet  videos/*.mp4  meta/*")
        print("  ────────────────────────────────────────────────────")

    # ---------------------------------------------------------- 收尾
    def close(self) -> None:
        """确保 parquet footer 写完（不写会导致数据集读不出来）。"""
        try:
            self.lerobot_saver.close()
        except Exception as e:                                # noqa: BLE001
            print("[warn] LeRobot 收尾异常: %s: %s" % (type(e).__name__, e))


# =================================================================== CLI
def main() -> int:
    ap = argparse.ArgumentParser(
        description="OrcaLab 双臂遥操作 + 数据采集（LeRobot v3.0）")
    # --- LeRobot ---
    ap.add_argument("--lerobot-out", required=True,
                    help="LeRobot 数据集输出根目录（必须是专用子目录）")
    ap.add_argument("--repo-id", default="local/manipulation",
                    help="LeRobot repo_id（默认 local/manipulation）")
    ap.add_argument("--fps", type=int, default=20,
                    help="采集帧率，写入 meta（默认 20，与遥操作循环一致）")
    ap.add_argument("--resume", action="store_true",
                    help="追加到已有数据集（断点续采）")
    ap.add_argument("--task-desc", default="teleop",
                    help="任务语言描述，写入 meta")

    # --- 遥操作参数（与 collect.py 对齐）---
    ap.add_argument("--task", default="teleop", help="任务名")
    ap.add_argument("--rot6d", action="store_true")
    ap.add_argument("--camera", action="store_true")
    ap.add_argument("--camera-ws", type=int, default=None, metavar="PORT")
    ap.add_argument("--camera-dir", default=None)
    ap.add_argument("--camera-addr", default="127.0.0.1:50051")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--keyboard", action="store_true")
    ap.add_argument("--reset-key", default=None)
    ap.add_argument("--no-reset-in-rec", action="store_true")
    ap.add_argument("--behind", action="store_true")
    ap.add_argument("--flip-lr", action="store_true")
    ap.add_argument("--flip-fb", action="store_true")
    ap.add_argument("--view", default=None)
    ap.add_argument("--env-index", type=int, default=None)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--addr", default=None)
    args = ap.parse_args()

    from teleop_view import parse_flags, resolve
    view = resolve(args.view) if args.view else parse_flags(
        args.behind, args.flip_lr, args.flip_fb)
    reset_key = args.reset_key or ("N" if args.keyboard else "RSTICK")

    bot = CollectTeleopLeRobot(
        lerobot_out=args.lerobot_out,
        repo_id=args.repo_id,
        fps=args.fps,
        task_desc=args.task_desc,
        resume=args.resume,
        task=args.task,
        camera_port=(args.camera_ws if args.camera_ws else (1 if args.camera else None)),
        camera_grpc=(args.camera_ws is None),
        camera_dir=args.camera_dir,
        camera_addr=args.camera_addr,
        reset_key=reset_key,
        reset_in_recording=not args.no_reset_in_rec,
        include_rotation_6d=args.rot6d,
        render=not args.no_render,
        pad_index=args.index,
        view=view,
        keyboard=args.keyboard,
        env_index=args.env_index,
        agent=args.agent,
        addr=args.addr,
    )

    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n[中断] 收到 Ctrl+C，正在收尾...")
    finally:
        bot.close()
        n = bot.rec.n_saved
        print("[LeRobot] 本次共保存 %d 条 episode" % n)
        print("[LeRobot] 数据集目录：%s" % os.path.abspath(args.lerobot_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
