# -*- coding: utf-8 -*-
"""机器人自带三相机 —— 走 OrcaGym 官方 WebSocket 推流（CameraRecorder）。

为什么是这个方案
================
26.8.1 起，相机走 OrcaStudio 自己的相机注册表（`env.get_camera_names()` 可见），
**不再依赖 MuJoCo 的 `<camera>` 元素**。所以机器人的三个彩色相机端口真的推流了：

    camera_head   7070   640x480x3  30Hz
    camera_left   7080   640x480x3  30Hz
    camera_right  7090   640x480x3  30Hz

实测 150 帧输入 -> 每路收到 148 帧（丢帧 1.3%，编解码抖动，正常）。

拿不到画面时的三个坑（缺一不可，别重复走）
------------------------------------------
* 坑A  env 构造必须 render_mode="force"（或 "human"），否则 render() 直接 return。
* 坑B  env.render(simulate_index=递增的整数) —— 内部 _current_simulate_index 初值 -1，
      不显式递增则引擎判定「同一帧」，只推 1 帧。
* 坑C  首次 render 要 request_idr=True 触发关键帧，否则解码器等不到 IDR。
* 补充 仿真必须是「外部控制」模式，由客户端脚本 do_simulation 驱动。

本模块只负责「收流 + 解码」，**不驱动仿真**。仿真驱动由调用方负责
（collect.py 里是 OrcaRig.step；独立自测见文件末尾的 __main__）。

用法（与 view_camera.ViewportCameraFeed 接口对齐）
--------------------------------------------------
    feed = WsCameraFeed()
    feed.open()
    frames = feed.grab_multi()     # {"head": ndarray(H,W,3) RGB, "left":..., "right":...}
    feed.grab()                    # 兼容单图接口 -> 返回 head
    feed.frame_size()              # (H, W)
    feed.stats()                   # 诊断信息
    feed.close()

注意：返回的是 **RGB**（OrcaGym 解码即 RGB）。如果要用 cv2.imwrite 存盘再肉眼看，
先用 cv2.cvtColor(img, cv2.COLOR_RGB2BGR)，否则红蓝会换。
"""
from __future__ import annotations

import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 机器人自带的三个彩色相机：tag -> (OrcaGym 相机名, 彩色推流端口)
DEFAULT_TARGETS = (
    ("head",  "camera_head",  7070),
    ("left",  "camera_left",  7080),
    ("right", "camera_right", 7090),
)

# 需要软件旋转 180° 的相机 —— 目前为空。
#
# 曾经的误判（留档，避免以后重复走）：
#   一度以为 camera_left 朝向反了 180°（因为画面里夹爪占比很大），
#   于是加了旋转。后来实测推翻了：移动**左臂**时 left 画面变化 59.6，
#   且夹爪在画面里的位置会随左臂关节改变而移动 —— 说明它是正常的外视角，
#   夹爪是"被拍到的对象"，不是"自拍"。
#
# left 画面信息量少的真正原因：相机沿视线方向离夹爪很近（约 10cm），
#   配上 90° 竖直 FOV 广角，导致画面被夹爪和近处遮挡物占满。
#   这是**安装位置**问题，需要改资产挪相机，不是软件能修的。
#
# 如将来确实需要翻转某路，把 tag 名加进这个元组即可。
ROTATE_TAGS = ()


class _CamStream:
    """单路相机：包一层 orca_gym.recorder.CameraRecorder。

    为什么不用 decode_frame_at（它已被官方标记 deprecated）
    ------------------------------------------------------
    decode_frame_at 每次新建 CodecContext、无 DPB 状态，遇到 P 帧就解不出来
    （只能靠回溯最近的 I 帧）。官方推荐路径是让 save_worker 线程维护**持久**
    CodecContext 实时解码，主线程通过 SingleFrameTask.on_frame 回调拿解码帧。

    这里正是走官方推荐路径：
      * 接收线程每收一帧 -> 内部自动提交 DecodeTask（更新 DPB）
      * 我们再提交 SingleFrameTask(target_idx, on_frame)，回调里直接读
        recorder.last_decoded_frame —— 同线程 FIFO 保证回调时解码已完成。
    """

    def __init__(self, tag: str, name: str, port: int,
                 poll_hz: float = 60.0, timeout: float = 1.0,
                 rotate180: bool = False):
        self.tag = tag
        self.name = name
        self.port = int(port)
        self.poll_hz = float(poll_hz)
        self.timeout = float(timeout)
        # 该路画面是否需要在软件层转 180°（见 ROTATE_TAGS 说明）
        self.rotate180 = bool(rotate180)

        self.rec = None
        self.ok = False
        self.error = ""

        self._lock = threading.Lock()
        self._latest = None          # ndarray(H,W,3) RGB
        self._latest_idx = None      # 对应的 simulate_index
        self._submitted = -1         # 已提交的最大 simulate_index（避免重复提交）
        self._pending = {}           # sim_idx -> Future
        self._frames = 0
        self._drops = 0
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------ 生命周期
    def open(self) -> bool:
        try:
            sys.path.insert(0, HERE)
            from orca_boot import redirect_report      # noqa: F401
            from orca_gym.recorder import CameraRecorder
        except Exception as e:                          # noqa: BLE001
            self.error = "导入失败: %s: %s" % (type(e).__name__, e)
            return False
        try:
            self.rec = CameraRecorder(camera_name=self.name, port=self.port)
            self.rec.start()
        except Exception as e:                          # noqa: BLE001
            self.error = "启动失败(端口 %d): %s: %s" % (self.port,
                                                  type(e).__name__, e)
            return False
        self.ok = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        period = 1.0 / max(1.0, self.poll_hz)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:                       # noqa: BLE001
                self.error = "%s: %s" % (type(e).__name__, e)
            time.sleep(period)

    def _tick(self) -> None:
        """提交新帧的回调任务，并收割已完成的 Future。"""
        from orca_gym.recorder.recording_task import SingleFrameTask
        rec = self.rec
        if rec is None:
            return
        # 1) 有新帧 -> 提交 SingleFrameTask（按 simulate_index 精确对齐）
        try:
            latest = rec.get_latest_simulate_index()
        except Exception:                                # noqa: BLE001
            latest = None
        if latest is not None and latest > self._submitted:
            start = max(self._submitted + 1, latest - 2)   # 最多补 3 帧，别追太远
            for idx in range(start, latest + 1):
                if idx in self._pending:
                    continue
                try:
                    fut = rec.submit_task(SingleFrameTask(idx, self._on_frame))
                except Exception:                        # noqa: BLE001
                    break
                self._pending[idx] = fut
                self._submitted = idx
                self._frames += 1

        # 2) 收割已完成的，取最新一张
        done = [i for i, f in self._pending.items() if f.done()]
        for idx in done:
            fut = self._pending.pop(idx)
            try:
                arr = fut.result()
            except Exception as e:                       # noqa: BLE001
                self.error = "解码失败 idx=%d: %s" % (idx, e)
                continue
            if arr is None:
                self._drops += 1
                continue
            frame = np.asarray(arr)
            if self.rotate180:
                # 等价 cv2.ROTATE_180（左右+上下都翻转），纯 numpy 避免依赖 cv2
                frame = np.ascontiguousarray(frame[::-1, ::-1])
            with self._lock:
                self._latest = frame
                self._latest_idx = idx

        # 3) 防堆积：FIFO 不该积压；万一积压就丢掉最老的
        if len(self._pending) > 240:
            for idx in sorted(self._pending)[:120]:
                self._pending.pop(idx, None)

    @staticmethod
    def _on_frame(frame_entry, decoded_frame):
        """save_worker 线程回调：直接返回已解码的 RGB 帧。"""
        return decoded_frame

    # ------------------------------------------------------------ 取帧
    def grab(self):
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    @property
    def latest_index(self):
        with self._lock:
            return self._latest_idx

    def stats(self) -> dict:
        d = {"tag": self.tag, "camera": self.name, "port": self.port,
             "ok": self.ok, "error": self.error,
             "frames": self._frames, "drops": self._drops}
        if self.rec is not None:
            try:
                d.update({("rec_" + k): v for k, v in self.rec.get_stats().items()})
            except Exception:                            # noqa: BLE001
                pass
        return d

    def close(self) -> None:
        self.ok = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._pending.clear()
        if self.rec is not None:
            try:
                self.rec.stop()
            except Exception:                            # noqa: BLE001
                pass
            self.rec = None


class WsCameraFeed:
    """三相机收流（head / left / right），走 OrcaGym WebSocket。

    与 view_camera.ViewportCameraFeed 接口对齐，可以直接替换：
        open() / grab() / grab_multi() / frame_size() / close() / stats()

    frames 是 **RGB**；ViewportCameraFeed 返回的是 BGR（视口 PNG 走 cv2 解码）。
    落盘器（LeRobot）写视频时会 convert("RGB")，所以用 RGB 才是正确顺序。
    """

    def __init__(self, targets=None, first_frame_timeout: float = 10.0,
                 rotate_tags=None):
        self.targets = tuple(targets or DEFAULT_TARGETS)
        self.first_frame_timeout = float(first_frame_timeout)
        # None -> 用默认 ROTATE_TAGS；传 () 可完全关闭校正
        self.rotate_tags = tuple(ROTATE_TAGS if rotate_tags is None
                                 else rotate_tags)
        self.channels: dict[str, str] = {}
        self.ok = False
        self.error = ""
        self._streams: list[_CamStream] = []

    # ------------------------------------------------------------ 打开
    def open(self, driver=None) -> bool:
        """连三路 WebSocket。

        Parameters
        ----------
        driver : callable | None
            每次「推进一步仿真」的无参函数。端口连上后引擎**不会自己出图**，
            必须有东西驱动 do_simulation + render。传 None 表示调用方自己驱动。
        """
        streams = []
        for tag, name, port in self.targets:
            s = _CamStream(tag, name, port,
                           rotate180=(tag in self.rotate_tags))
            if not s.open():
                for x in streams:
                    x.close()
                self.error = "%s 打不开: %s" % (name, s.error)
                return False
            streams.append(s)
            self.channels[tag] = name

        # 等首帧。
        #
        # 判定用 received_first_idr（不是「解码出图」）：H.264 要先等到 IDR
        # 关键帧解码器才能起，收到 IDR 就说明推流链路真的通了。
        # driver 必须被高频调用 —— 引擎在外部控制模式下**不会自己出图**，
        # 每推进一步仿真才会送一帧。
        #
        # 注意：三路 WebSocket 是**串行**连接的（每路 ~2s），连接时间不能
        # 算进首帧预算，所以计时从这里（三路都连上之后）开始。
        t0 = time.time()
        while time.time() - t0 < self.first_frame_timeout:
            if driver is not None:
                try:
                    driver()
                except Exception as e:                   # noqa: BLE001
                    self.error = "驱动仿真失败: %s: %s" % (type(e).__name__, e)
                    break
            else:
                time.sleep(1.0 / 30.0)
            if all(getattr(s.rec, "received_first_idr", False) for s in streams):
                break

        # 再给解码线程一点时间把首帧解出来
        t1 = time.time()
        while time.time() - t1 < 2.0:
            if driver is not None:
                try:
                    driver()
                except Exception:                        # noqa: BLE001
                    pass
            else:
                time.sleep(1.0 / 30.0)
            if all(s.grab() is not None for s in streams):
                break

        got = {s.tag: (s.grab() is not None) for s in streams}
        if not any(got.values()):
            for s in streams:
                s.close()
            idr = {s.tag: bool(getattr(s.rec, "received_first_idr", False))
                   for s in streams}
            self.error = ("%.1f 秒内三路都没收到画面（首IDR=%s）。检查："
                          "1) 仿真是否在跑 2) 是否『外部控制』模式 "
                          "3) render_mode 是否为 force 4) simulate_index 是否在递增"
                          % (self.first_frame_timeout, idr))
            return False

        self._streams = streams
        self.ok = True
        return True

    # ------------------------------------------------------------ 取帧
    def grab_multi(self) -> dict:
        """返回 {tag: ndarray(H,W,3) RGB}；未就绪的通道为 None。"""
        return {s.tag: s.grab() for s in self._streams}

    def grab(self):
        """兼容单图接口：优先 head，其次任意一路。"""
        d = self.grab_multi()
        for tag in [t for t, _, _ in self.targets]:
            if d.get(tag) is not None:
                return d[tag]
        return None

    def frame_size(self) -> tuple[int, int]:
        """返回首帧的 (H, W)；还没抓到帧时返回 (0, 0)。

        给 LeRobot 落盘器推导图像 feature 的真实尺寸用
        （LeRobot 默认 720x1280，与实际 480x640 不符会直接报错）。
        """
        for s in self._streams:
            img = s.grab()
            if img is not None and img.ndim == 3:
                return int(img.shape[0]), int(img.shape[1])
        return (0, 0)

    def stats(self) -> dict:
        return {s.tag: s.stats() for s in self._streams}

    def close(self) -> None:
        self.ok = False
        for s in self._streams:
            s.close()
        self._streams = []


# =================================================================== 自测
def _self_test() -> int:
    """独立自测：自己驱动仿真 + render，验证三路都能出画面。

    需要：OrcaStudio 已打开场景、仿真处于「外部控制」模式。
    """
    import argparse
    ap = argparse.ArgumentParser(description="三相机 WebSocket 自测")
    ap.add_argument("--addr", default="127.0.0.1:50051")
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default=os.path.join(HERE, "out_final"))
    args = ap.parse_args()

    from orca_gym.environment.orca_gym_local_env import OrcaGymLocalEnv

    print("连接引擎 %s ..." % args.addr)
    env = OrcaGymLocalEnv(frame_skip=20, orcagym_addr=args.addr,
                          agent_names=["camselftest"], time_step=0.001,
                          render_mode="force")
    env.initialize_grpc()
    env.initialize_simulation()
    env.set_sync_render(False)
    env.set_render_fps(args.fps)
    print("  模型 nq=%s nv=%s nu=%s" % (env.model.nq, env.model.nv, env.model.nu))
    try:
        print("  引擎相机: %s" % list(env.get_camera_names()))
    except Exception as e:                               # noqa: BLE001
        print("  get_camera_names 失败: %s" % e)

    idx = [-1]

    def drive():
        ctrl = np.zeros(env.model.nu, dtype=np.float32)
        env.do_simulation(ctrl, 20)
        idx[0] += 1
        env.render(simulate_index=idx[0], request_idr=(idx[0] == 0))

    print("打开三相机 ...")
    feed = WsCameraFeed()
    if not feed.open(driver=drive):
        print("失败:", feed.error)
        env.close()
        return 1
    print("通道:", feed.channels)

    import cv2
    interval = 1.0 / max(1, args.fps)
    tnext = time.time()
    shots = 0
    for i in range(args.steps):
        drive()
        frames = feed.grab_multi()
        if i == args.steps - 1 or i == args.steps // 2:
            os.makedirs(args.out, exist_ok=True)
            for tag, img in frames.items():
                if img is not None:
                    fp = os.path.join(args.out, "ws_%s_%03d.png" % (tag, i))
                    cv2.imwrite(fp, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
                    print("  saved", fp)
                    shots += 1
        tnext += interval
        s = tnext - time.time()
        if s > 0:
            time.sleep(s)

    print()
    print("统计:")
    for tag, st in feed.stats().items():
        print("  %-6s %dx%d 帧=%s 丢=%s 缓冲=%s 首IDR=%s 连接=%s"
              % (tag,
                 (feed.grab_multi().get(tag).shape[1]
                  if feed.grab_multi().get(tag) is not None else 0),
                 (feed.grab_multi().get(tag).shape[0]
                  if feed.grab_multi().get(tag) is not None else 0),
                 st.get("frames"), st.get("drops"),
                 st.get("rec_buffered_frames"), st.get("rec_received_first_idr"),
                 st.get("rec_is_connected")))
    feed.close()
    env.close()
    print("完成，存图 %d 张 -> %s" % (shots, args.out))
    return 0 if shots else 2


if __name__ == "__main__":
    raise SystemExit(_self_test())
