# -*- coding: utf-8 -*-
u"""用「官方流程」接机器人自载三相机。

和 ws_camera.py 的区别
======================
ws_camera.py 是**自己** new CameraRecorder(camera_name, port) 然后 .start()，
相当于绕过 env 层直接连端口。它有两个隐患：

  1. 端口是**写死**的 (7070/7080/7090)。一旦 OrcaStudio 里改了推流端口，
     代码就连到空气上，且现象是「连上了、但永远收不到帧」，极难查。
  2. 没有调用引擎侧的 ``set_streaming_enabled(True)``。推流没打开时，
     WebSocket 能连、但一帧不来 —— 正是之前反复踩的坑。

官方流程（orca_gym 的推荐路径，见 recorder/video_recorder.py
``VideoRecorderManager.start_recorder`` 与 environment/orca_gym_local_env.py
``start_streaming``）是让 **env 层**代劳：

    env.get_camera_names()                  # 枚举「已注册」相机
    env.start_streaming(name, **kwargs)     # ★ 查属性 -> 必要时停流重配
                                            #   -> set_streaming_enabled(True)
                                            #   -> 按 capture_rgb 建并启动 recorder
    mgr = env.get_recorder_manager()
    rec = mgr.get_recorder(name, "color")   # 端口由后端属性给出，不用写死

本模块就按这个流程走。取帧仍用官方 ``SingleFrameTask`` + ``last_decoded_frame``
（持久 CodecContext，P 帧不用回溯）。

帧是 **RGB**（OrcaGym 解码即 rgb24）。
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

# 三路相机的 tag -> OrcaStudio 里的相机注册名（端口不写死，由后端属性给出）
DEFAULT_CAMERAS = (
    ("head",  "camera_head"),
    ("left",  "camera_left"),
    ("right", "camera_right"),
)

#: 软件层补 180° 旋转的 tag（目前无）。见 ws_camera.ROTATE_TAGS 的长注释。
ROTATE_TAGS = ()


class OfficialCameraFeed:
    u"""三相机收流 —— 走 env.start_streaming() 官方流程。

    接口与 ws_camera.WsCameraFeed 对齐，可直接替换：
        open(env) / grab_multi() / grab() / frame_size() / channels / close() / stats()
    """

    def __init__(self, cameras=None, first_frame_timeout: float = 15.0,
                 poll_hz: float = 60.0, rotate_tags=None,
                 stream_kwargs=None):
        self.cameras = tuple(cameras or DEFAULT_CAMERAS)
        self.first_frame_timeout = float(first_frame_timeout)
        self.poll_hz = float(poll_hz)
        rot = ROTATE_TAGS if rotate_tags is None else tuple(rotate_tags)
        self.rotate_tags = tuple(rot)
        # ★ 开推流时传给 env.start_streaming() 的参数。
        # capture_rgb=True 是关键：不传的话后端默认
        # capture_rgb=False，彩色流不会起，get_recorder
        # 始终返回 None，表现为“接上了但没画面”。
        if stream_kwargs is None:
            stream_kwargs = {"capture_rgb": True}
        self.stream_kwargs = dict(stream_kwargs)

        self.env = None
        self.manager = None
        # tag -> 状态字典
        self.streams = {}
        self.error = ""
        self.ok = False
        self.channels = []          # 成功接上的 tag 列表
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._frames = 0
        self._drops = 0

    # ---------------------------------------------------------------- 启动
    def open(self, env) -> bool:
        u"""env 为 OrcaGym env（OrcaRig 里是 r.u）。"""
        self.env = env
        self.error = ""

        # 1) 枚举后端**已注册**的相机名（权威来源，别靠猜）
        try:
            registered = list(env.get_camera_names())
        except Exception as e:                              # noqa: BLE001
            self.error = "get_camera_names 失败: %s: %s" % (type(e).__name__, e)
            return False
        if not registered:
            self.error = ("后端未注册任何相机（env.get_camera_names() 为空）。"
                          "确认仿真处于「运行/外部控制」状态。")
            return False

        try:
            self.manager = env.get_recorder_manager()
        except Exception as e:                              # noqa: BLE001
            self.error = "get_recorder_manager 失败: %s: %s" % (type(e).__name__, e)
            return False

        missing = []
        for tag, name in self.cameras:
            if name not in registered:
                missing.append("%s(%s)" % (tag, name))
                continue
            # 2) ★ 官方入口：查属性 -> 开推流 -> 建并启动 recorder
            try:
                env.start_streaming(name, **self.stream_kwargs)
            except Exception as e:                          # noqa: BLE001
                self.error = ("start_streaming('%s') 失败: %s: %s"
                              % (name, type(e).__name__, e))
                continue
            rec = self.manager.get_recorder(name, "color")
            if rec is None:
                self.error = ("start_streaming('%s', %s) 后仍取不到 recorder。\n"
                              "  通常是彩色流没开：确认 stream_kwargs "
                              "里有 capture_rgb=True；\n"
                              "  也可能该相机本身没有彩色传感器。"
                              % (name, self.stream_kwargs))
                continue
            port = None
            try:
                port = int(getattr(rec, "port", 0)) or None
            except Exception:                               # noqa: BLE001
                port = None
            self.streams[tag] = {
                "tag": tag, "name": name, "rec": rec, "port": port,
                "latest": None, "latest_idx": None,
                "submitted": -1, "pending": {}, "err": "",
            }

        if missing:
            print("[official-cam] 后端没有这些相机: %s" % ", ".join(missing),
                  flush=True)
        if not self.streams:
            if not self.error:
                self.error = "三路相机一路都没起来"
            return False

        # 3) 等首帧（推流是异步的，render 驱动后才来）
        if not self._wait_first_frames():
            # 已接上但还没帧 —— 不算失败，交给主循环继续驱动
            print("[official-cam] 已连接但首帧未到（主循环会继续驱动仿真）",
                  flush=True)

        self.ok = True
        self.channels = [t for t, _ in self.cameras if t in self.streams]
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _wait_first_frames(self) -> bool:
        deadline = time.time() + self.first_frame_timeout
        while time.time() < deadline:
            self._tick()
            if all(s["latest"] is not None for s in self.streams.values()):
                return True
            time.sleep(0.1)
        return False

    # ---------------------------------------------------------------- 收帧
    def _loop(self) -> None:
        period = 1.0 / max(1.0, self.poll_hz)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:                          # noqa: BLE001
                self.error = "%s: %s" % (type(e).__name__, e)
            time.sleep(period)

    def _tick(self) -> None:
        u"""提交官方 SingleFrameTask，并收割已完成的 Future。"""
        try:
            from orca_gym.recorder.recording_task import SingleFrameTask
        except Exception:                                   # noqa: BLE001
            return
        for st in list(self.streams.values()):
            rec = st["rec"]
            if rec is None:
                continue
            try:
                latest = rec.get_latest_simulate_index()
            except Exception:                               # noqa: BLE001
                latest = None
            if latest is not None and latest > st["submitted"]:
                start = max(st["submitted"] + 1, latest - 2)   # 最多补 3 帧
                for idx in range(start, latest + 1):
                    if idx in st["pending"]:
                        continue
                    try:
                        fut = rec.submit_task(
                            SingleFrameTask(idx, self._on_frame))
                    except Exception:                       # noqa: BLE001
                        break
                    st["pending"][idx] = fut
                    st["submitted"] = idx
                    self._frames += 1

            done = [i for i, f in st["pending"].items() if f.done()]
            for idx in done:
                fut = st["pending"].pop(idx)
                try:
                    arr = fut.result()
                except Exception as e:                      # noqa: BLE001
                    st["err"] = "解码失败 idx=%d: %s" % (idx, e)
                    continue
                if arr is None:
                    self._drops += 1
                    continue
                frame = np.asarray(arr)
                if st["tag"] in self.rotate_tags:
                    frame = np.ascontiguousarray(frame[::-1, ::-1])
                with self._lock:
                    st["latest"] = frame
                    st["latest_idx"] = idx

            if len(st["pending"]) > 240:                    # 防堆积
                for idx in sorted(st["pending"])[:120]:
                    st["pending"].pop(idx, None)

    @staticmethod
    def _on_frame(frame_entry, decoded_frame):
        u"""save_worker 线程回调：直接给已解码的 RGB 帧。"""
        return decoded_frame

    # ---------------------------------------------------------------- 取帧
    def grab_multi(self) -> dict:
        out = {}
        with self._lock:
            for tag, st in self.streams.items():
                if st["latest"] is not None:
                    out[tag] = st["latest"].copy()
        return out

    def grab(self):
        return self.grab_multi().get("head")

    def frame_size(self) -> tuple[int, int]:
        for st in self.streams.values():
            if st["latest"] is not None:
                return int(st["latest"].shape[0]), int(st["latest"].shape[1])
        return (0, 0)

    def latest_index(self):
        idx = None
        with self._lock:
            for st in self.streams.values():
                if st["latest_idx"] is not None:
                    idx = st["latest_idx"] if idx is None \
                        else max(idx, st["latest_idx"])
        return idx

    def stats(self) -> dict:
        s = {"ok": self.ok, "error": self.error, "channels": list(self.channels),
             "frames": self._frames, "drops": self._drops, "cameras": {}}
        for tag, st in self.streams.items():
            d = {"camera": st["name"], "port": st["port"], "err": st["err"],
                 "latest_idx": st["latest_idx"],
                 "has_frame": st["latest"] is not None}
            try:
                d.update({("rec_" + k): v for k, v in st["rec"].get_stats().items()})
            except Exception:                               # noqa: BLE001
                pass
            s["cameras"][tag] = d
        return s

    # ---------------------------------------------------------------- 收尾
    def close(self) -> None:
        self.ok = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        # 关闭推流（官方配对的 set_streaming_enabled(False)）
        for tag, st in self.streams.items():
            try:
                if self.manager is not None:
                    self.manager.stop_recorder(st["name"])
            except Exception:                               # noqa: BLE001
                pass
            try:
                if self.env is not None:
                    self.env.get_recorder_manager().set_streaming_enabled(
                        st["name"], False)
            except Exception:                               # noqa: BLE001
                pass
            st["pending"].clear()
            st["rec"] = None
        self.streams.clear()
