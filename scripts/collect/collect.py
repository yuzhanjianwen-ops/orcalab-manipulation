# -*- coding: utf-8 -*-
"""主采集脚本：遥操作 + 按键状态机 + HDF5 落盘。

这是把已经写好并测过的四个模块"总装"起来的地方：

    recorder.py    状态机 + episode 内存缓冲   （纯逻辑，已测 27 项）
    keymap.py      十字键 -> 状态机（边沿检测） （已测 11 项）
    fields.py      每帧字段采集                 （依赖 OrcaRig）
    saver_hdf5.py  HDF5 落盘                    （已测 14 项）

本脚本负责：连接仿真、跑遥操作主循环、每个控制周期喂一帧给 recorder。

相机
----
相机走 **gRPC `GetCameraFramePNG`**（实测可用，见 `相机资产接入实操.md`）：
加 `--camera` 即开，图像存进 `observations/image`，形状 (T,H,W,3) uint8。

> 注：老的 WebSocket 方式（`CameraWrapper` + 端口 7070）需要资产里有
> MuJoCo `<camera>` 传感器；当前机器人 `ncam=0`，拿不到帧。
> 想试老方式用 `--camera-ws 7070`。

用法
----
    # 手柄，右手臂，存到默认数据集目录
    python collect.py

    # 键盘（无手柄时）
    python collect.py --keyboard

    # 自定义数据集目录 / 任务名
    python collect.py --dataset D:\\data\\pick --task pick_medbox

    # 带相机（gRPC 取图，推荐）
    python collect.py --camera

按键（手柄 / 键盘两套并行，互不影响）
------------------------------------
    十字下  待命 / 取消 / 中止
    十字上  开始 / 结束录制
    十字左  保存
    十字右  丢弃

    （键盘对应 I / K / J / L）

原有的遥操作按键完全不受影响（A/B 夹爪、X 切换手臂 …）。
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- 采集模块内部导入 ------------------------------------------------
sys.path.insert(0, HERE)
from recorder import Recorder, State                 # noqa: E402
from keymap import DpadRecorder                      # noqa: E402
from fields import FrameGrabber                      # noqa: E402
from saver_hdf5 import Hdf5Saver                     # noqa: E402
from view_camera import ViewportCameraFeed           # noqa: E402

# 三相机（OrcaGym WebSocket 推流）+ LeRobot 直存（新）
# 任一模块导入失败都不致命：采集照常，只是少了那个能力。
try:
    from ws_camera import WsCameraFeed
except Exception as _e:                                # noqa: BLE001
    WsCameraFeed = None
    print("[warn] ws_camera 不可用: %s: %s" % (type(_e).__name__, _e))
try:
    from saver_lerobot_v3 import LeRobotSaver, lerobot_available
except Exception as _e:                                # noqa: BLE001
    LeRobotSaver = None
    def lerobot_available():
        return False, '%s: %s' % (type(_e).__name__, _e)

# ---- 复用遥操作模块（同一个文件夹，自包含）--------------------------
TELEOP_DIR = os.environ.get("ORCA_TELEOP_DIR") or os.path.join(
    os.path.dirname(HERE), "teleop")
if not os.path.isdir(TELEOP_DIR):
    raise SystemExit(
        "找不到遥操作模块目录：%s\n"
        "请用环境变量 ORCA_TELEOP_DIR 指向 teleop 文件夹。" % TELEOP_DIR)
sys.path.insert(0, TELEOP_DIR)
os.chdir(TELEOP_DIR)

# 复用参数与常量，保证采集时的手感与 teleop.py 完全一致
from teleop import (                                             # noqa: E402
    Teleop, LIN_SPEED, ANG_SPEED, GRIP_RATE, GRIP_OPEN, GRIP_CLOSE, BOX,
)
import teleop as teleop_mod                                      # noqa: E402
from teleop_view import parse_flags, resolve                     # noqa: E402


def _extend_keypad_reset_key() -> None:
    """给键盘驱动补一个复位键（默认 N）。

    keypad.py 的 VK 表里没有 N，而采集时需要一个独立的复位键
    （原版 teleop.py 用「十字下」，采集时被状态机占用了）。

    只补 VK 码，**不动** _BUTTON_ALIASES / DEFAULT_BINDINGS ——
    因为 Keypad.poll() 会遍历 _BUTTON_ALIASES 去查 BUTTON_MASKS，
    塞进未注册的别名会让 poll() 直接 KeyError。
    复位键的读取走 key_down('N')，不经过按钮掩码体系。
    """
    try:
        import keypad as kp
    except Exception:                                        # noqa: BLE001
        return
    kp.VK.setdefault("N", 0x4E)          # N = 0x4E
    kp.VK.setdefault("M", 0x4D)          # M = 0x4D（双臂镜像开关）


_extend_keypad_reset_key()


# =================================================================== 相机
class CameraFeed:
    """相机包装：连不上就自动降级为 None（采集照常）。"""

    def __init__(self, port: int, name: str = "camera"):
        self.port = int(port)
        self.name = name
        self.cam = None
        self.ok = False
        self.error = ""

    def open(self) -> bool:
        try:
            sys.path.insert(0, HERE)
            from orca_boot import redirect_report     # noqa: F401
            from orca_gym.sensor.rgbd_camera import CameraWrapper
        except Exception as e:                        # noqa: BLE001
            self.error = "导入相机模块失败: %s: %s" % (type(e).__name__, e)
            return False
        try:
            self.cam = CameraWrapper(name=self.name, port=self.port)
            self.cam.start()
        except Exception as e:                        # noqa: BLE001
            self.error = "相机启动失败: %s: %s" % (type(e).__name__, e)
            return False
        t0 = time.time()
        while time.time() - t0 < 3.0:
            try:
                if self.cam.is_first_frame_received():
                    self.ok = True
                    return True
            except Exception:                          # noqa: BLE001
                break
            time.sleep(0.05)
        self.error = ("%d 秒内没收到首帧（端口 %d）——相机可能没在推流"
                      % (3, self.port))
        return False

    def grab(self):
        if not self.ok or self.cam is None:
            return None
        try:
            img = self.cam.image
            return None if img is None else np.asarray(img)
        except Exception:                              # noqa: BLE001
            return None

    def close(self) -> None:
        if self.cam is not None:
            try:
                self.cam.stop()
            except Exception:                          # noqa: BLE001
                pass


# =========================================================== 相机（gRPC）
class GrpcCameraFeed:
    """相机取图 —— 走 OrcaStudio 的 gRPC `GetCameraFramePNG`。

    为什么用它（而不是 CameraWrapper）
    ----------------------------------
    `CameraWrapper` 走 WebSocket(7070)，要求资产里有 MuJoCo `<camera>`
    传感器；当前机器人模型 `ncam=0`，推流拿不到帧。
    而 `GetCameraFramePNG` 是让 Studio 主动渲染一次并落盘，**实测可用**。

    坑（重要）
    ----------
    `GetCameraFramePNGRequest.image_path` 传的是**目录**，不是文件！
    服务端会在该目录下写：
        color/AgentCamera_color_0.png
        depth/AgentCamera_depth_0.npy
        normal/AgentCamera_normal_0.png
        object_color/AgentCamera_object_color_0.png
    而且**异步落盘** —— gRPC 返回时文件可能还没写完，所以要轮询等。

    本类只取 `color` 那张（和原 CameraFeed 的接口保持一致：
    `grab()` 返回 (H,W,3) uint8）。深度/分割图留在磁盘上备用。
    """

    def __init__(self, addr: str = "127.0.0.1:50051", name: str = "camera",
                 tmpdir: str | None = None, timeout: float = 5.0):
        self.addr = addr
        self.name = name
        self.timeout = timeout
        self.ok = False
        self.error = ""
        self.camera_name = ""
        self.stub = None
        self.pb = None
        self.tmpdir = tmpdir or os.path.join(HERE, "_camera_tmp")
        self._frame_dir = None
        self._primed = False
        self._last = None
        # 后台解码线程：PNG 解码 1080x1080 约 44ms，
        # 同步做会吃掉 20fps 控制周期(50ms) 的全部余量 —— 所以丢到后台。
        self._thread = None
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._latest = None          # 最近一帧(已解码, BGR uint8)
        self._latest_idx = 0         # 帧序号，便于判断是否新帧
        self.decode_fps = 0.0

    # -------------------------------------------------------------- 打开
    def open(self) -> bool:
        try:
            sys.path.insert(0, HERE)
            from orca_boot import redirect_report      # noqa: F401
            import grpc
            from orca_gym.protos import mjc_message_pb2, mjc_message_pb2_grpc
        except Exception as e:                          # noqa: BLE001
            self.error = "导入 gRPC 模块失败: %s: %s" % (type(e).__name__, e)
            return False
        try:
            self.pb = mjc_message_pb2
            self.stub = mjc_message_pb2_grpc.GrpcServiceStub(
                grpc.insecure_channel(self.addr))
            os.makedirs(self.tmpdir, exist_ok=True)
            self._frame_dir = os.path.join(self.tmpdir, "frame")
            os.makedirs(self._frame_dir, exist_ok=True)
        except Exception as e:                          # noqa: BLE001
            self.error = "初始化失败: %s: %s" % (type(e).__name__, e)
            return False

        # 先同步取一帧（同时把通路"点燃"：_primed + camera_name），
        # 这样失败能立刻给出明确原因。
        buf = self._fetch_bytes()
        if buf is None:
            if not self.error:
                self.error = ("gRPC 取图失败（%s）——仿真没启动？"
                              "或 OrcaStudio 没开？" % self.addr)
            return False
        import cv2
        img = cv2.imdecode(np.frombuffer(buf, dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            self.error = "首帧解码失败（%d 字节）" % len(buf)
            return False
        with self._lock:
            self._latest = img

        self.ok = True
        # 起后台解码线程，主循环只取"最近一帧"（非阻塞）
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()
        return True

    # -------------------------------------------------------------- 取帧
    def grab(self):
        """返回最近一帧 (H,W,3) uint8 BGR；还没就绪则返回 None。

        性能（实测）
        ------------
        这是**非阻塞**的：只取后台线程解好的最新帧，约 **0.01 ms**。
        真正耗时的部分（读盘 1ms + PNG 解码 44ms）在后台线程里做，
        渲染端约 27Hz，所以图像实际更新率约 20~27 fps。
        """
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def _decode_loop(self) -> None:
        """后台循环：读盘 -> 解码 -> 存到 _latest。"""
        import cv2
        cnt, t0 = 0, time.time()
        while not self._stop_evt.is_set():
            try:
                buf = self._fetch_bytes()
                if buf is None:
                    time.sleep(0.01)
                    continue
                arr = np.frombuffer(buf, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    with self._lock:
                        self._latest = img
                        self._latest_idx += 1
                    cnt += 1
                    now = time.time()
                    if now - t0 >= 1.0:
                        self.decode_fps = cnt / (now - t0)
                        cnt, t0 = 0, now
            except Exception as e:                      # noqa: BLE001
                self.error = "解码线程: %s: %s" % (type(e).__name__, e)
                time.sleep(0.05)

    def _fetch_bytes(self):
        """返回最新一帧的 PNG 字节；超时返回 None。

        性能设计（重要，实测得出）
        --------------------------
        OrcaStudio 的渲染端**自己就在跑**（实测约 27 Hz，文件持续被更新），
        **不需要每帧都调 gRPC 去"催"**。

        早期实现每帧都发一次 `GetCameraFramePNG`，结果反而**更慢**
        （中位 60ms，还周期性卡 500ms）—— 每次请求会触发一次同步重渲染，
        和渲染端互相抢。

        现在：`open()` 里调一次确认通路；之后 `grab()` **只读盘**（1~2ms）。
        """
        if not self._primed:
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                req = self.pb.GetCameraFramePNGRequest(image_path=self._frame_dir)
                resp = self.stub.GetCameraFramePNG(req, timeout=self.timeout)
                try:
                    name = resp.name_transform[0].name if resp.name_transform else ""
                except Exception:                       # noqa: BLE001
                    name = ""
                if name:
                    self.camera_name = name
                    self._primed = True
                    break
                time.sleep(0.005)
            if not self._primed:
                return None

        color = os.path.join(self._frame_dir, "color",
                             "%s_color_0.png" % self.camera_name)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                with open(color, "rb") as fh:
                    buf = fh.read()
                if buf:
                    return buf
            except (FileNotFoundError, PermissionError, OSError):
                pass
            time.sleep(0.001)
        return None

    def close(self) -> None:
        self.ok = False
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.stub = None
        self.pb = None


# =================================================================== 提示
def remember_location(dataset: str, task: str) -> str:
    """把数据集位置写到一个固定文件里，方便以后查找。

    文件：本目录/DATASET_LOCATION.txt
    """
    path = os.path.join(HERE, "DATASET_LOCATION.txt")
    lines = [
        "OrcaLab 数据采集 —— 数据集位置备忘",
        "=" * 56,
        "",
        "最新一次采集的数据集目录：",
        "  " + os.path.abspath(dataset),
        "",
        "任务名  : %s" % task,
        "更新时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "-" * 56,
        "结构说明",
        "-" * 56,
        "  每个 episode 一个子目录，名字格式：",
        "      2026-09-28_164713_96b72dde/",
        "      <日期>_<时分秒>_<8位随机码>/",
        "          episode.hdf5   实际数据（HDF5）",
        "          meta.json      元信息（帧数/时长/字段形状）",
        "",
        "-" * 56,
        "常用命令",
        "-" * 56,
        "  用资源管理器打开：",
        "    explorer \"%s\"" % os.path.abspath(dataset),
        "",
        "  看目录内容：",
        "    dir \"%s\"" % os.path.abspath(dataset),
        "",
    ]
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass
    return path


def banner(rec: Recorder, cam, dataset: str) -> None:
    print()
    print("=" * 66)
    print("  OrcaLab 双臂遥操作 · 数据采集")
    print("=" * 66)
    print("  数据集目录 :", os.path.abspath(dataset))
    if cam.ok:
        if WsCameraFeed is not None and isinstance(cam, WsCameraFeed):
            ch = ", ".join("%s=%s" % (k, v) for k, v in cam.channels.items())
            hw = cam.frame_size()
            print("  相机       : 已连接 (机器人自带三相机 WebSocket, %s)" % ch)
            if hw[0]:
                print("               分辨率 %dx%d, 30Hz" % (hw[1], hw[0]))
        elif isinstance(cam, ViewportCameraFeed):
            ch = ", ".join("%s=#%d" % (k, v) for k, v in cam.channels.items())
            print("  相机       : 已连接 (G1 三相机, %s)" % ch)
        elif isinstance(cam, GrpcCameraFeed):
            print("  相机       : 已连接 (gRPC 取图, 相机=%s)" % cam.camera_name)
        else:
            print("  相机       : 已连接 (端口 %d)" % cam.port)
    else:
        print("  相机       : 未连接 —— 只采状态数据（无 image 字段）")
        if cam.error:
            print("               原因:", cam.error)
    print()
    print("  十字下 = 待命 / 取消 / 中止")
    print("  十字上 = 开始 / 结束录制")
    print("  十字左 = 保存    十字右 = 丢弃")
    print("  （键盘：I=上 K=下 J=左 L=右）")
    print("  复位     = 全场景复位（物体+双臂+夹爪回起点）")
    print("  M        = 双臂镜像联动（操作一臂时另一臂同步镜像）")
    print("=" * 66)
    print("  当前：", rec.status_line())
    print()
    print("  ★ 数据保存到上面那个『数据集目录』里，每个 episode 一个子目录")
    print("  ★ 路径已记录到 DATASET_LOCATION.txt，忘了可以看它")
    print()


# =================================================================== 主循环
class CollectTeleop(Teleop):
    """在 Teleop 的基础上叠一层采集：每个控制周期喂一帧。"""

    def __init__(self, dataset: str, task: str = "teleop",
                 camera_port: int | None = None, include_rotation_6d: bool = False,
                 reset_key: str = "RSTICK", reset_in_recording: bool = True,
                 camera_grpc: bool = True, camera_dir: str | None = None,
                 camera_addr: str = "127.0.0.1:50051", cam3: bool = False,
                 cam3_ws: bool = False, allow_floating_camera: bool = False,
                 no_camera: bool = False,
                 lerobot_out: str | None = None,
                 lerobot_fps: int = 20, lerobot_resume: bool = False,
                 lerobot_videos: bool = True, **kw):
        super().__init__(**kw)
        self.dataset = dataset
        # 复位键（替代原版 teleop.py 的「十字下」全场景重启）
        self.reset_key = reset_key
        # 录制过程中是否也允许复位。默认允许 —— 便于一个 episode 里
        # 连续做多次「抓取->放下->复位->再抓」的动作。
        self.reset_in_recording = bool(reset_in_recording)
        self._prev_reset = False
        self._reset_events = 0        # 本 episode 内复位了几次（写进 meta）

        # ---- 采集三件套 ---------------------------------------------
        # 落盘器二选一：
        #   * --lerobot-out DIR  -> LeRobot v3.0（默认；直接产出可训练的数据集）
        #   * 否则               -> HDF5（老格式，每条 episode 一个子目录）
        self.lerobot_out = lerobot_out
        self.saver = None
        self.hdf5_saver = None
        if lerobot_out:
            ok, why = lerobot_available()
            if not ok:
                raise SystemExit(
                    "指定了 --lerobot-out 但 lerobot 不可用：\n  %s\n"
                    "请先安装： pip install \"lerobot[dataset]>=0.6.1\" pyarrow av" % why)
            self.saver = LeRobotSaver(
                root=lerobot_out, repo_id="local/" + str(task),
                fps=lerobot_fps, task=task, resume=lerobot_resume,
                use_videos=lerobot_videos,
                # cameras 留空 -> 从第一帧图像自动推导尺寸（省得手填错）
                # 采集路径必须有图像：接不到帧就明报错，
                # 而不是静默写出一个没图像的数据集。
                require_cameras=True,
            )
            print("[lerobot] 直接落 LeRobot v3.0 数据集 -> %s  (fps=%d, videos=%s, resume=%s)"
                  % (lerobot_out, lerobot_fps, lerobot_videos, lerobot_resume), flush=True)
        else:
            self.hdf5_saver = Hdf5Saver(dataset, task_name=task)
            self.saver = self.hdf5_saver
        self.rec = Recorder(on_event=self._on_rec_event)
        self.rec.set_saver(self.saver)
        self.grabber = FrameGrabber(
            self.r, active_arm=lambda: self.active,
            include_rotation_6d=include_rotation_6d)
        self.dpad_rec = DpadRecorder(self.rec, self.pad,
                                     on_message=self._on_rec_event_msg)

        # ---- 双臂镜像联动 -------------------------------------------
        # 按 M 切换。开启后：操作活动臂时，另一臂做关于「机身对称面」的镜像运动。
        # 对称面 = 机体系的 YZ 平面（x=0）。实测两臂中性位姿在机体系下：
        #     左臂 [0.221, +1.596, 1.617]
        #     右臂 [0.225, -1.599, 1.617]   <- y 恰好互为相反数
        # 所以镜像 = 把机体系下的 y 取反，姿态同步做镜像（含手性修正）。
        self.mirror_active = False
        self._prev_mirror_key = False
        # 镜像的两个"锚点"：各自的中性位姿。镜像始终相对锚点算，
        # 这样两臂从各自 home 出发同步移动，不会累积漂移。
        self.mirror_anchor = {s: [self.home_pose[s][0].copy(),
                                  self.home_pose[s][1].copy()]
                              for s in ("l", "r")}

        # ---- 仿真帧计数（推流用；必须严格递增）-----------------------
        # 注意：必须在相机 open() 之前初始化 —— open() 会调 _drive_sim，
        # 而 _drive_sim 要读它。放后面会 AttributeError（且被 open 内部吞掉，
        # 表现成「相机怎么都接不上」这种极难查的现象）。
        self._sim_idx = -1

        # ---- 相机 ---------------------------------------------------
        # 相机来源（按优先级）—— ★ 默认就是【机器人自带三相机】，不是 Studio 的悬浮相机。
        #   0) cam3_ws=True   -> ★ 机器人自带三相机 camera_head/left/right，
        #                         走 OrcaGym WebSocket 推流 7070/7080/7090，30Hz。**默认**
        #   1) cam3=True      -> 同样这三台相机，但走 Studio 视口渲染（~0.6fps，慢）
        #   2) 单路 gRPC/WS   -> 旧路径：Studio 离屏 **AgentCamera（悬浮相机）**，
        #                         它不属于机器人；必须显式 allow_floating_camera 才允许
        #
        # 为什么默认改成机载相机：Studio 主视口 / AgentCamera 是一台悬在场景里的
        # 自由相机（viewport index 0，scale=1.0），采出来的画面和机器人真正看到的
        # 不是一个视角，也不是同一个分辨率。
        self.cam3 = None
        self.use_cam3 = bool(cam3)
        self.use_cam3_ws = bool(cam3_ws)
        single_port = camera_port

        # 单路 gRPC == 悬浮 AgentCamera -> 默认拒绝（避免悄悄采到错的画面）
        if single_port and camera_grpc and not allow_floating_camera:
            raise SystemExit(
                "拒绝使用【悬浮相机】(Studio 离屏 AgentCamera) —— 它不是机器人身上的相机。\n"
                "\n"
                "  数据采集请用机器人自带三相机：\n"
                "      --cam3-ws    机器人自带三相机 · WebSocket 推流（推荐，30Hz）\n"
                "      --cam3       机器人自带三相机 · Studio 视口渲染（慢）\n"
                "\n"
                "  确实要用悬浮相机：显式加 --allow-floating-camera\n"
                "  完全不要图像    ：加 --no-camera")

        # 一个相机开关都没给 -> 默认接入机载三相机（WebSocket）
        if not (self.use_cam3_ws or self.use_cam3 or single_port or no_camera):
            self.use_cam3_ws = True
            print("[cam] 未指定相机开关：默认接入【机器人自带三相机】"
                  " camera_head / camera_left / camera_right "
                  "(WebSocket 7070/7080/7090)。", flush=True)

        if self.use_cam3_ws:
            self.cam = WsCameraFeed()
        elif self.use_cam3:
            self.cam = ViewportCameraFeed()
        elif single_port:
            if camera_grpc:
                self.cam = GrpcCameraFeed(name="camera", tmpdir=camera_dir,
                                          addr=camera_addr)
            else:
                self.cam = CameraFeed(single_port)
        else:
            self.cam = GrpcCameraFeed()          # 占位，不 open

        if self.use_cam3_ws:
            # 关键：WebSocket 收流要有东西驱动仿真（do_simulation + render）。
            # 这里用 OrcaRig 的 step 做「空推一步」——真正的主循环每周期也会步进，
            # open() 期间只是为了让首帧尽快到达。
            if self.cam.open(driver=lambda: self._drive_sim(self.r.ctrl())):
                self.cam3 = self.cam
                self.rec.set_images_fn(self._grab3_dict)
                print("[cam3-ws] 三相机已接入(WebSocket 推流):", self.cam.channels,
                      flush=True)
                print("[cam3-ws] 落盘字段: " + ", ".join(
                    "image_%s" % k for k in self.cam.channels), flush=True)
            else:
                print("[warn] 三相机(WS)没接上：%s" % self.cam.error, flush=True)
                print("[warn] 继续以无图像模式采集", flush=True)
        elif self.use_cam3:
            if self.cam.open():
                self.cam3 = self.cam
                # 多相机：三路图一起写进每一帧
                self.rec.set_images_fn(self._grab3_dict)
                print("[cam3] 三相机已接入:", self.cam.channels, flush=True)
                print("[cam3] 落盘字段: " + ", ".join(
                    "observations/image_%s" % k for k in self.cam.channels),
                    flush=True)
            else:
                print("[warn] 三相机没接上：%s" % self.cam.error, flush=True)
                print("[warn] 继续以无图像模式采集", flush=True)
        elif single_port:
            if self.cam.open():
                self.rec.set_image_fn(self.cam.grab)
            else:
                print("[warn] 相机没接上，继续以无图像模式采集", flush=True)

        banner(self.rec, self.cam, dataset)
        self.location_file = remember_location(dataset, task)

        # ---- 帧率统计 ------------------------------------------------
        self._fps_last = time.perf_counter()
        self._fps_frame = 0
        self._last_status = ""

    # -------------------------------------------------------- 双臂镜像
    def _mirror_pose(self, src_side: str, dst_side: str):
        """把 src 臂相对自身锚点的位移，镜像到 dst 臂的锚点上。

        为什么不用「直接镜像绝对位姿」
        ------------------------------
        绝对镜像要求两臂初始位姿严格对称，而实测只差 0.005m 左右
        （[0.2206,1.5955,1.6165] vs [0.2252,-1.5990,1.6165]）。
        直接镜像绝对位姿会把这点误差当成"初始偏差"永久保留；
        而用「相对锚点的位移」镜像，则两臂从各自 home 出发、
        增量严格对称，手感一致。

        数学
        ----
        设机体系下镜像算子 M：(x, y, z) -> (x, -y, z)。
        世界系下  M_w = Rb @ M_b @ Rb^T   （Rb = base_rot，正交矩阵）

        姿态用旋转矩阵 R 表示。镜像一个旋转需要**手性修正**：
            R_mirrored = M_w @ R @ diag(1, -1, 1)
        最后那个 diag(1,-1,1) 是用来抵消镜像带来的左右手反转，
        否则姿态里的 y/z 轴方向会反（夹爪朝向会错）。

        Returns
        -------
        (pos, mat) 镜像后 dst 臂的目标位姿；失败返回 None。
        """
        try:
            a_src = self.mirror_anchor[src_side]
            a_dst = self.mirror_anchor[dst_side]
            g_src = self.goal[src_side]

            # 锚点在机体系下的镜像一致性检查（只算一次，偏差过大给警告）
            Rb = self.Rb

            # 位移（世界系）-> 机体系
            d_src_w = np.asarray(g_src[0], float) - np.asarray(a_src[0], float)
            d_src_b = Rb.T @ d_src_w
            # 机体系镜像：y 取反
            d_mir_b = np.array([d_src_b[0], -d_src_b[1], d_src_b[2]], float)
            # 回世界系，贴到 dst 锚点上
            pos = np.asarray(a_dst[0], float) + Rb @ d_mir_b

            # 姿态：先取相对旋转，再镜像
            R_src = np.asarray(g_src[1], float)
            R_a_src = np.asarray(a_src[1], float)
            R_rel = R_a_src.T @ R_src          # 相对锚点的旋转（世界系）

            # 世界系镜像算子：M_w = Rb @ diag(1,-1,1) @ Rb^T
            Mb = np.diag([1.0, -1.0, 1.0])
            Mw = Rb @ Mb @ Rb.T
            R_rel_mir = Mw @ R_rel @ Mb       # 手性修正：右侧再乘 Mb
            mat = np.asarray(a_dst[1], float) @ R_rel_mir
            return pos, mat
        except Exception:                                # noqa: BLE001
            return None

    def _toggle_mirror(self) -> None:
        """M 键：切换双臂镜像联动。"""
        self.mirror_active = not self.mirror_active
        if self.mirror_active:
            # 重新取锚点 = 当前两臂实际位姿，保证从"现在这里"开始同步
            for side in ("l", "r"):
                self.osc[side].hold()
                self.mirror_anchor[side] = [
                    self.osc[side].site_pos.copy(),
                    self.osc[side].site_mat.copy(),
                ]
            print("\n[镜像] 已开启 —— 操作 %s 臂时，另一臂同步镜像"
                  % self.active.upper(), flush=True)
        else:
            print("\n[镜像] 已关闭", flush=True)

    # -------------------------------------------------------- 推进仿真
    def _drive_sim(self, ctrl=None) -> None:
        """推进一步仿真并渲染 —— **显式递增 simulate_index**。

        为什么单独写这一个方法
        ----------------------
        OrcaRig.step() 内部调的是 self.u.render()（不带参数），
        引擎在「外部控制」模式里会把它当成「同一帧」，**只推 1 帧**。
        要让相机持续推流，必须每次传一个严格递增的整数。
        """
        self._sim_idx += 1
        self.r._hold()
        self.r.u.set_ctrl(ctrl)
        self.r.u.do_simulation(ctrl, self.r.u.frame_skip)
        self.r._hold()
        if self.render:
            self.r.u.render(simulate_index=self._sim_idx,
                            request_idr=(self._sim_idx == 0))

    # -------------------------------------------------------- 三相机取帧
    def _grab3(self):
        """取三路相机；返回拼接后的 dict 供 Recorder 使用。

        Recorder.set_image_fn 只接受一个 ndarray，所以这里返回
        「主图」= head 画面，同时把另外两路挂到实例上，
        由 capture 后处理写入。简单起见：返回 head 图。
        （三路同时入库见 _grab3_dict / --cam3-dict）
        """
        d = self.cam3.grab_multi() if self.cam3 is not None else {}
        self._last3 = d
        return d.get("head")

    def _grab3_dict(self):
        """三路原图，供需要多相机的落盘器使用。"""
        if self.cam3 is None:
            return {}
        return self.cam3.grab_multi()

    # ------------------------------------------------------------ 回调
    def _on_rec_event(self, kind: str, msg: str) -> None:
        tag = {"save": "★ 已保存", "discard": "× 已丢弃",
               "review": "待判定", "error": "!! 错误"}.get(kind, kind)
        print("\n[%s] %s" % (tag, msg), flush=True)
        if kind == "save":
            try:
                self._verify_last_episode()
            except Exception as e:                       # noqa: BLE001
                print("[自检] 校验出错: %s: %s" % (type(e).__name__, e),
                      flush=True)

    # -------------------------------------------------------- 实时格式自检
    def _verify_last_episode(self) -> None:
        """每存完一条 episode，当场报告数据格式（形状/维度/图像统计）。"""
        eps = self.rec.saved_episodes
        if not eps:
            return
        ep = eps[-1]
        data = ep.stacked()
        n = ep.n_frames
        print("-" * 62, flush=True)
        print("  格式自检  episode %d  %d 帧" % (ep.episode_id, n), flush=True)
        print("-" * 62, flush=True)

        # ---- 向量字段 ----
        for k in ("joint_pos", "gripper_pos", "ee_pos", "ee_quat",
                  "action_pos", "action_quat", "action_gripper"):
            v = data.get(k)
            if v is None:
                print("  %-12s 缺" % k, flush=True)
            else:
                print("  %-12s %s" % (k, str(tuple(v.shape))), flush=True)

        # ---- 拼出来的 observation.state / action ----
        try:
            state = np.stack([np.concatenate([
                np.asarray(data["joint_pos"][i]).reshape(-1),
                np.asarray(data["gripper_pos"][i]).reshape(-1),
                np.asarray(data["ee_pos"][i]).reshape(-1),
                np.asarray(data["ee_quat"][i]).reshape(-1)]) for i in range(n)])
            print("  => observation.state  %s   (44 期望)"
                  % str(tuple(state.shape)), flush=True)
        except Exception as e:                           # noqa: BLE001
            print("  => observation.state  拼装失败: %s" % e, flush=True)

        # ---- 图像 ----
        for tag in ("head", "left", "right"):
            arr = data.get("image_%s" % tag)
            if arr is None:
                print("  image_%-6s 缺" % tag, flush=True)
                continue
            imgs = [np.asarray(a) for a in arr if a is not None]
            if not imgs:
                print("  image_%-6s 全空" % tag, flush=True)
                continue
            a0 = imgs[0]
            # RGB 顺序粗检：这三个相机拍的是偏灰/偏冷的桌面场景，
            # 若 R/B 反了，R 和 B 的均值会明显拉开（>25）。
            r, g, b = (a0[..., 0].mean(), a0[..., 1].mean(),
                       a0[..., 2].mean())
            flag = "  ← 疑似 R/B 反了" if abs(r - b) > 25 else ""
            print("  image_%-6s (%d,%d,%d) x%d  R=%.0f G=%.0f B=%.0f%s"
                  % (tag, a0.shape[0], a0.shape[1], a0.shape[2], len(imgs),
                     r, g, b, flag), flush=True)

        # ---- LeRobot 回读校验 ----
        if self.lerobot_out:
            self._reload_check()

    def _reload_check(self) -> None:
        """用 LeRobotDataset 把刚写的数据集读回来，核对 feature 形状。"""
        try:
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
        except Exception as e:                           # noqa: BLE001
            print("  [回读] lerobot 不可用: %s" % e, flush=True)
            return
        try:
            ds = LeRobotDataset(repo_id="local/check",
                                root=self.lerobot_out, video_backend="pyav")
            s0 = ds[0]
            print("  [回读] LeRobotDataset 共 %d 帧 / %d 集"
                  % (len(ds), ds.meta.total_episodes), flush=True)
            for k in sorted(s0):
                v = s0[k]
                shape = getattr(v, "shape", None)
                if shape is not None and len(shape):
                    print("         %-32s %s" % (k, tuple(shape)), flush=True)
        except Exception as e:                           # noqa: BLE001
            print("  [回读] 失败: %s: %s" % (type(e).__name__, e), flush=True)

    def _on_rec_event_msg(self, msg: str) -> None:
        print("\n[采集] " + msg, flush=True)

    # ------------------------------------------------------------ 镜像键
    def _mirror_key_held(self) -> bool:
        """M 键当前是否按住。

        与复位键 N 同理：不走按钮掩码体系（keypad 表里没有 M），
        直接用 GetAsyncKeyState 读物理键状态。
        手柄模式下退化为 False（手柄没有对应按键）。
        """
        try:
            import keypad as kp
            return bool(kp.key_down("M"))
        except Exception:                                # noqa: BLE001
            return False

    # ------------------------------------------------------------ 复位键
    def _reset_held(self) -> bool:
        """复位键当前是否按住。

        手柄：默认 RSTICK（右摇杆按下去），走 Gamepad.held。
        键盘：Keypad 没有摇杆按压，改用独立键 N，直接读物理键状态
              （不走按钮掩码，避免污染 keypad 的 BUTTON_MASKS 表）。
        """
        if self.reset_key in ("N", "reset", "RESET"):
            try:
                import keypad as kp
                return bool(kp.key_down("N"))
            except Exception:                                # noqa: BLE001
                return False
        try:
            return bool(self.pad.held(self.reset_key))
        except Exception:                                    # noqa: BLE001
            return False

    # ------------------------------------------------------------ 状态
    def _status_bar(self) -> None:
        line = self.rec.status_line() + "  |  已保存 %d 条" % self.rec.n_saved
        if line != self._last_status:
            print("\n" + line, flush=True)
            self._last_status = line

    # ------------------------------------------------------------ 主循环
    def run(self) -> None:
        dt = self.r.dt
        frame = 0
        print("teleop+采集 运行中。Ctrl-C 停止\n", flush=True)
        try:
            while True:
                t0 = time.perf_counter()
                self.pad.poll()

                # ==== 采集按键：优先处理，且与遥操作按键不冲突 ========
                # 只有十字键归采集状态机；A/B/X/Y/START/BACK 照旧归遥操作。
                _prev_state = self.rec.state
                self.dpad_rec.poll()
                # 刚进入 RECORDING：复位计数清零（每条 episode 单独统计）
                if _prev_state is not State.RECORDING \
                        and self.rec.state is State.RECORDING:
                    self._reset_events = 0

                # ==== 遥操作按键（与 teleop.py 完全一致） =============
                if self.pad.pressed("X"):
                    from teleop_view import select_arm, screen_side
                    self.active = select_arm(self.active, self.view)
                    note = ""
                    if self.view.mirrored:
                        note = "  (on screen: %s)" % screen_side(
                            self.active, self.view).upper()
                    print("\nactive arm ->", self.active.upper() + note, flush=True)
                if self.pad.pressed("Y"):
                    self.go_home(self.active)
                    print("\nhome", self.active.upper(), flush=True)
                if self.pad.pressed("START"):
                    self.resync(self.active)
                    print("\nresync", self.active.upper(), flush=True)

                # ==== M 键：双臂镜像联动开关 ==========================
                # 用「物理键直读 + 边沿检测」，理由同复位键 N：
                # keypad 的按钮掩码表里没有 M，走 held() 会一路 False。
                mk = self._mirror_key_held()
                if mk and not self._prev_mirror_key:
                    self._toggle_mirror()
                self._prev_mirror_key = mk

                # ==== 复位（原版 teleop.py 用「十字下」）=================
                # 采集模式下十字下归采集状态机，不能再兼作重启，
                # 所以把「全场景复位」挪到独立的复位键上（默认 RSTICK）。
                # 只有 IDLE 状态才允许复位，录制/待判定时拒绝，防止误触丢数据。
                rk = self._reset_held()
                if rk and not self._prev_reset:
                    st = self.rec.state
                    if st is State.IDLE or self.reset_in_recording:
                        if st is State.RECORDING:
                            self._reset_events += 1
                        self.full_restart()
                        if st is State.RECORDING:
                            print("\n[复位] 已复位（录制中第 %d 次，数据继续记录）"
                                  % self._reset_events, flush=True)
                    else:
                        print("\n[!] 正在采集（%s），复位已忽略"
                              " —— 先按 K 结束/中止再复位" % st.value, flush=True)
                self._prev_reset = rk
                if rk:
                    # 按住复位键时不要同时触发视角切换，避免误操作
                    rst = False
                else:
                    rst = self.pad.held("RSTICK")
                if rst and not self._prev_rstick:
                    stock = parse_flags(False, False, False)
                    self.view = stock if self.view.mirrored or self.view.flip_fb \
                        else self.view_saved
                    print("\ncontrol frame ->", self.view.describe(), flush=True)
                self._prev_rstick = rst
                frozen = self.pad.held("BACK")

                # ==== 夹爪 ============================================
                g = self.grip_cmd[self.active]
                if self.pad.held("A"):
                    g -= GRIP_RATE * dt
                if self.pad.held("B"):
                    g += GRIP_RATE * dt
                self.grip_cmd[self.active] = float(np.clip(g, GRIP_CLOSE, GRIP_OPEN))
                # 镜像开启时，另一臂夹爪跟随同一条开合指令
                if self.mirror_active:
                    other = "r" if self.active == "l" else "l"
                    self.grip_cmd[other] = self.grip_cmd[self.active]

                # ==== 运动 ============================================
                side = self.active
                if not frozen:
                    lx, ly = self.pad.left
                    rx, ry = self.pad.right
                    lx, ly = self.view.apply(lx, ly)
                    if self.view.flip_lr:
                        rx = -rx
                    v = np.array([ly, lx, self.pad.rt - self.pad.lt]) * LIN_SPEED
                    self.goal[side][0] = self.goal[side][0] + self.Rb @ (v * dt)

                    w = np.array([rx, ry,
                                  self.pad.held("RB") - self.pad.held("LB")]) * ANG_SPEED
                    M = (teleop_mod.rot_z(w[0] * dt)
                         @ teleop_mod.rot_y(w[1] * dt)
                         @ teleop_mod.rot_x(w[2] * dt))
                    self.goal[side][1] = self.goal[side][1] @ M

                    hp = self.home_pose[side][0]
                    d = self.goal[side][0] - hp
                    self.goal[side][0] = hp + np.clip(d, -BOX, BOX)

                # ==== 镜像联动 ========================================
                # 操作活动臂后，把它的位移镜像到另一臂。
                #
                # 【关键 bug 修复】
                # 旧代码只写 self.goal[other]，但下面下发时 set_goal 只对
                # side（活动臂）调用 —— other 臂的 goal 改了却从没下发，
                # 所以仿真里另一只手臂根本不动。
                # 现在把「实际下发的臂」记进 self._dl_sides，确保两臂都 set_goal。
                self._dl_sides = [side]
                if self.mirror_active:
                    other = "r" if side == "l" else "l"
                    mp = self._mirror_pose(side, other)
                    if mp is not None:
                        pos, mat = mp
                        # 同样做 box 限幅（相对另一臂自己的 home）
                        hp = self.home_pose[other][0]
                        dd = pos - hp
                        self.goal[other][0] = hp + np.clip(dd, -BOX, BOX)
                        self.goal[other][1] = mat
                        self._dl_sides = [side, other]

                # ==== 下发 ============================================
                # 镜像开启时两臂都要 set_goal（见上面 _dl_sides 的说明）
                for _s in getattr(self, "_dl_sides", [side]):
                    self.osc[_s].set_goal(self.goal[_s][0], self.goal[_s][1])
                c = self.r.ctrl()
                for s in ("l", "r"):
                    c = self._apply_osc(c, self.osc[s])
                c = self._apply_grip(c)
                # ---- 关键：外部控制模式下必须递增 simulate_index，引擎才推流 ----
                # OrcaRig.step -> self.u.render() 用的是内部自增的 _current_simulate_index，
                # 在「外部控制」模式里这个值不一定在涨；我们显式传一个递增的整数
                # 覆盖它，同时首帧 request_idr=True 触发关键帧（否则解码器等不到 IDR）。
                # 传 simulate_index 时顺便自己 do_simulation，避免重复步进一帧。
                self._drive_sim(c)

                # ==== 采集这一帧 ======================================
                if self.rec.state is State.RECORDING:
                    action = {
                        "goal_pos": self.goal[side][0],
                        "goal_mat": self.goal[side][1],
                        "gripper_cmd": self.grip_cmd[side],
                    }
                    frame_data = self.grabber(action)
                    # 把「复位次数」也存进每一帧，方便后续切分/分析
                    frame_data["n_resets"] = np.float32(self._reset_events)
                    self.rec.capture(frame_data)

                # ==== 显示 ============================================
                frame += 1
                if frame % 25 == 0:
                    now = time.perf_counter()
                    fps = 25.0 / max(1e-6, now - self._fps_last)
                    self._fps_last = now
                    st = self.rec.status_line(fps)
                    if self.mirror_active:
                        st += "  [镜像 ON]"
                    # pinch 是向量（两个指垫），取前 3 位显示
                    pinch = np.asarray(self.osc[side].pinch, float).ravel()
                    ptxt = "/".join("%.3f" % v for v in pinch[:3])
                    print("[%s] pinch=%s err=%.1fmm grip=%+.2f fps=%.1f | %s"
                          % (side.upper(), ptxt,
                             1000 * self.osc[side].err_to(self.goal[side][0]),
                             self.grip_cmd[side], fps, st), flush=True)

                # ==== 节拍 ============================================
                slack = dt - (time.perf_counter() - t0)
                if slack > 0:
                    time.sleep(slack)

        except KeyboardInterrupt:
            print("\n\n停止中 ...", flush=True)
        finally:
            self._shutdown()

    # ------------------------------------------------------------ 收尾
    def _shutdown(self) -> None:
        # 录到一半被打断：提醒用户数据没存
        if self.rec.state is State.RECORDING:
            print("!! 退出时仍在录制，这一条 **没有保存**"
                  "（%d 帧已丢弃）" % self.rec.episode.n_frames, flush=True)
        elif self.rec.state is State.REVIEW:
            print("!! 退出时还有一条待判定，**没有保存**"
                  "（按十字左才是保存）", flush=True)

        print()
        print("=" * 66)
        print("  本次采集结束")
        print("  保存成功 : %d 条" % self.rec.n_saved)
        print("  丢弃     : %d 条" % self.rec.n_discarded)
        for i, ep in enumerate(self.rec.saved_episodes):
            print("    [%d] ep%-3d  %4d 帧  %5.1fs"
                  % (i, ep.episode_id, ep.n_frames, ep.duration))
        print("  数据集目录:", os.path.abspath(self.dataset))
        print("  路径备忘  :", self.location_file)
        print("=" * 66)

        self.cam.close()
        # LeRobot：必须收尾一次才会写 parquet footer，否则数据读不出来
        if getattr(self, "saver", None) is not None:
            try:
                self.saver.close()
            except Exception as e:                       # noqa: BLE001
                print("[lerobot] [warn] 收尾失败: %s: %s" % (type(e).__name__, e),
                      flush=True)
        try:
            self.r.close()
        except Exception:                                # noqa: BLE001
            pass


# =================================================================== CLI
def main() -> int:
    ap = argparse.ArgumentParser(
        description="OrcaLab 双臂遥操作 + 数据采集（HDF5）")
    # --- 数据集 ---
    ap.add_argument("--dataset", default=os.path.join(HERE, "dataset"),
                    help="数据集目录（默认 ./dataset）")
    ap.add_argument("--task", default="teleop", help="任务名，写入 meta")
    ap.add_argument("--rot6d", action="store_true",
                    help="额外保存 6D 旋转表示 action_rot6d")
    # --- 相机 ---
    ap.add_argument("--camera", action="store_true",
                    help="[已弃用/默认拒绝] 单路取图，走 gRPC GetCameraFramePNG —— "
                         "它拍的是 Studio 离屏 **悬浮相机 AgentCamera**，不是机器人相机。"
                         "要用必须再加 --allow-floating-camera；"
                         "想采机器人相机请用 --cam3-ws")
    ap.add_argument("--camera-ws", type=int, default=None, metavar="PORT",
                    help="[旧方式] 相机 WebSocket 端口（如 7070）。"
                         "需要资产内有 MuJoCo <camera> 传感器，当前不可用")
    ap.add_argument("--camera-dir", default=None,
                    help="相机临时目录（默认 ./_camera_tmp）")
    ap.add_argument("--camera-addr", default="127.0.0.1:50051",
                    help="OrcaStudio gRPC 地址")
    ap.add_argument("--cam3", action="store_true",
                    help="★ 接 G1 自带三相机 (head/wrist_l/wrist_r)，"
                         "走 OrcaStudio 视口渲染，三路图分别存进 "
                         "observations/image_head / image_wrist_l / image_wrist_r")
    ap.add_argument("--cam3-list", action="store_true",
                    help="只列出场景里的相机通道后退出（自检用）")
    ap.add_argument("--cam3-ws", action="store_true",
                    help="★ 机器人自带三相机走 OrcaGym WebSocket 推流"
                         "(7070/7080/7090, 640x480@30Hz)，每帧写 image_head/"
                         "image_left/image_right。**推荐，也是默认**")
    ap.add_argument("--allow-floating-camera", action="store_true",
                    help="[危险] 允许用 Studio 离屏 AgentCamera（悬浮相机）取图。"
                         "它悬在场景里、不属于机器人，视角与分辨率都和机载相机不同。"
                         "只在做对照实验时用。")
    ap.add_argument("--no-camera", action="store_true",
                    help="明确不接任何相机（纯 state/action 采集）")
    # --- LeRobot 直存 ---
    ap.add_argument("--lerobot-out", default=None, metavar="DIR",
                    help="★ 直接把 episode 存成 LeRobot v3.0 数据集到这个目录"
                         "（推荐）。不给则退回老 HDF5 格式。")
    ap.add_argument("--no-lerobot", action="store_true",
                    help="强制用 HDF5 落盘（即使给了 --dataset）")
    ap.add_argument("--lerobot-fps", type=int, default=20,
                    help="写进 LeRobot meta 的采集帧率（默认 20）")
    ap.add_argument("--lerobot-resume", action="store_true",
                    help="追加到已有 LeRobot 数据集（第二场接着上一场写）")
    ap.add_argument("--lerobot-stamp", dest="lerobot_stamp", action="store_true",
                    default=True,
                    help="[默认开] 自动在 --lerobot-out 后面加时间戳子目录，"
                         "每次启动写到一个新目录，永不撞名。")
    ap.add_argument("--no-lerobot-stamp", dest="lerobot_stamp",
                    action="store_false",
                    help="关掉时间戳（严格写进 --lerobot-out 本身；"
                         "此时目录非空会报错，除非加 --lerobot-resume）。")
    ap.add_argument("--lerobot-no-videos", action="store_true",
                    help="LeRobot 用 parquet 内嵌 PNG 而不是 mp4 视频")
    # --- 遥操作参数（与 teleop.py 对齐）---
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--keyboard", action="store_true",
                    help="用键盘代替手柄")
    ap.add_argument("--reset-key", default=None,
                    help="复位键名。手柄默认 RSTICK，键盘默认 N")
    ap.add_argument("--no-reset-in-rec", action="store_true",
                    help="禁止在录制过程中复位（默认允许）")
    ap.add_argument("--behind", action="store_true")
    ap.add_argument("--flip-lr", action="store_true")
    ap.add_argument("--flip-fb", action="store_true")
    ap.add_argument("--view", default=None)
    ap.add_argument("--env-index", type=int, default=None)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--addr", default=None)
    args = ap.parse_args()

    # ---- 快速拦截：别让"悬浮相机"被误用 -------------------------------
    if args.camera and not args.allow_floating_camera:
        print("=" * 66)
        print("  拒绝使用【悬浮相机】(Studio 离屏 AgentCamera)")
        print("=" * 66)
        print("  --camera 拍的是 Studio 里那台悬空的 AgentCamera，")
        print("  它不属于机器人，和机器人真正看到的画面不是同一个视角。")
        print()
        print("  数据采集请改用机器人自带三相机：")
        print("      --cam3-ws    机器人自带三相机 · WebSocket 推流（推荐，30Hz）")
        print("      --cam3       机器人自带三相机 · Studio 视口渲染（慢）")
        print()
        print("  确实要用悬浮相机：--camera --allow-floating-camera")
        print("  完全不要图像    ：--no-camera")
        print("=" * 66)
        return 2

    if args.cam3_list:
        f = ViewportCameraFeed()
        try:
            sys.path.insert(0, HERE)
            from orca_boot import redirect_report      # noqa: F401
            import grpc
            import orcalab.protos.edit_service_pb2 as ep
            import orcalab.protos.edit_service_pb2_grpc as epg
            stub = epg.GrpcServiceStub(grpc.insecure_channel("127.0.0.1:50151"))
            r = stub.GetCameras(ep.GetCamerasRequest(), timeout=15)
            print("场景相机 (%d):" % len(r.cameras))
            for c in r.cameras:
                print("   [%d] %-14s actor=%s (%s)"
                      % (c.index, c.name, c.actor_path or "-", c.source))
        except Exception as e:                          # noqa: BLE001
            print("列相机失败:", type(e).__name__, e)
            return 1
        return 0

    if args.view:
        view = resolve(args.view)
    else:
        view = parse_flags(args.behind, args.flip_lr, args.flip_fb)

    # 手柄：RSTICK（右摇杆按下）；键盘：N 键
    reset_key = args.reset_key or ("N" if args.keyboard else "RSTICK")

    lerobot_out = None if args.no_lerobot else args.lerobot_out

    # ---- 时间戳子目录：每次启动一个新目录，避免"目录已存在" --------------
    # 规则：  <你给的 --lerobot-out>\20261011_153042
    #   * --lerobot-resume 时不加（resume 就是要往同一个目录里续写）
    #   * --no-lerobot-stamp 时不加
    #   * 同一秒内重复启动也不会撞（自动补 _2 _3 ...）
    if lerobot_out and args.lerobot_stamp and not args.lerobot_resume:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = lerobot_out
        cand = os.path.join(base, stamp)
        n = 2
        while os.path.exists(cand):
            cand = os.path.join(base, "%s_%d" % (stamp, n))
            n += 1
        lerobot_out = cand
        print("[lerobot] 本次数据 -> %s" % lerobot_out, flush=True)
    elif lerobot_out and args.lerobot_resume:
        print("[lerobot] resume 模式，追加到 -> %s" % lerobot_out, flush=True)

    CollectTeleop(
        dataset=args.dataset,
        task=args.task,
        cam3=args.cam3,
        cam3_ws=args.cam3_ws,
        lerobot_out=lerobot_out,
        lerobot_fps=args.lerobot_fps,
        lerobot_resume=args.lerobot_resume,
        lerobot_videos=not args.lerobot_no_videos,
        camera_port=(args.camera_ws if args.camera_ws else (1 if args.camera else None)),
        camera_grpc=(args.camera_ws is None),
        camera_dir=args.camera_dir,
        camera_addr=args.camera_addr,
        allow_floating_camera=getattr(args, "allow_floating_camera", False),
        no_camera=getattr(args, "no_camera", False),
        include_rotation_6d=args.rot6d,
        reset_key=reset_key,
        reset_in_recording=not args.no_reset_in_rec,
        render=not args.no_render,
        pad_index=args.index,
        view=view,
        keyboard=args.keyboard,
        env_index=args.env_index,
        agent=args.agent,
        addr=args.addr,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
