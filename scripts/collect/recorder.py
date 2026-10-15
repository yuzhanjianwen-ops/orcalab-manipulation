# -*- coding: utf-8 -*-
"""数据采集核心：状态机 + 数据缓冲（与落盘格式、相机均无关）。

设计目标
--------
* 按键状态机：十字下=待命/取消，十字上=开始/结束，十字左=保存，十字右=丢弃
* 每步采集：关节状态、夹爪状态、末端位姿、动作指令
* 图像字段预留：相机就绪后由 `set_image_fn` 注入，无需改动本模块
* 落盘字段预留：格式确定后由 `set_saver` 注入

本模块**不依赖 orca_gym**，可以离线单测。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

import numpy as np


class State(str, Enum):
    """采集状态机。"""

    IDLE = "IDLE"          # 正常遥操作，不记录
    READY = "READY"        # 已武装，等待开始
    RECORDING = "REC"      # 正在录制
    REVIEW = "REVIEW"      # 录完，等待保存/丢弃


@dataclass
class EpisodeBuffer:
    """一条 episode 的内存缓冲。"""

    episode_id: int = 0
    frames: list[dict] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    success: Optional[bool] = None      # True=保存, False=丢弃
    note: str = ""

    # ---------------------------------------------------------------- 写入
    def append(self, frame: dict) -> None:
        self.frames.append(frame)

    # ---------------------------------------------------------------- 查询
    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def duration(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return 0.0

    def stacked(self) -> dict[str, np.ndarray]:
        """把逐帧 dict 堆叠成 {key: (T, ...) ndarray}，便于训练/落盘。

        图像字段（ndarray，且每帧形状一致）同样会被堆叠成 (T, H, W, C)。
        """
        if not self.frames:
            return {}
        keys = self.frames[0].keys()
        out: dict[str, np.ndarray] = {}
        for k in keys:
            vals = [f.get(k) for f in self.frames]
            if any(v is None for v in vals):
                out[k] = np.array([v for v in vals if v is not None])
                continue
            try:
                out[k] = np.stack(vals) if isinstance(vals[0], np.ndarray) \
                    else np.asarray(vals)
            except ValueError:
                # 形状不一致（例如图像分辨率变化）——退化为 object 数组
                out[k] = np.array(vals, dtype=object)
        return out

    def clear(self) -> None:
        self.frames.clear()
        self.started_at = self.finished_at = 0.0
        self.success = None
        self.note = ""


class Recorder:
    """采集状态机。按键语义由调用方翻译成这里的四个方法。

    典型用法::

        rec = Recorder()
        rec.arm()                     # 十字下
        while running:
            ...
            if rec.state is State.RECORDING:
                rec.capture(frame_dict)
            rec.tick(pressed=...)      # 或手工调用 start/stop/save/discard
    """

    def __init__(self, on_event: Optional[Callable[[str, str], None]] = None):
        self.state: State = State.IDLE
        self.episode: EpisodeBuffer = EpisodeBuffer()
        self._next_id: int = 0
        self._saved: list[EpisodeBuffer] = []
        self._discarded: int = 0
        self._on_event = on_event
        # 图像供给函数：返回 (H,W,3) uint8 或 None
        self._image_fn: Optional[Callable[[], Optional[np.ndarray]]] = None
        # 多相机供给函数：返回 {"head": ndarray, "wrist_l": ndarray, ...}
        # 注入后每帧会展开成 image_<name> 字段（image_head / image_wrist_l ...）
        self._images_fn: Optional[Callable[[], dict]] = None
        # 落盘回调：格式确定后注入
        self._saver: Optional[Callable[[EpisodeBuffer], str]] = None

    # ------------------------------------------------------------ 依赖注入
    def set_image_fn(self, fn: Callable[[], Optional[np.ndarray]]) -> None:
        """注入相机取帧函数；未注入时图像字段为 None。"""
        self._image_fn = fn

    def set_images_fn(self, fn: Callable[[], dict]) -> None:
        """注入多相机取帧函数（G1 三相机）。

        fn() 返回 {"head": (H,W,3) uint8, "wrist_l": ..., "wrist_r": ...}，
        每帧会被展开写成 image_head / image_wrist_l / image_wrist_r。
        """
        self._images_fn = fn

    def set_saver(self, fn: Callable[[EpisodeBuffer], str]) -> None:
        """注入落盘函数（LeRobot / HDF5 待定）；未注入时只留在内存。"""
        self._saver = fn

    # ---------------------------------------------------------------- 事件
    def _emit(self, kind: str, msg: str) -> None:
        if self._on_event:
            self._on_event(kind, msg)

    # ------------------------------------------------------------ 按键动作
    def arm(self) -> str:
        """十字下：进入待命；RECORDING 中则强制中止并丢弃。"""
        if self.state is State.IDLE:
            self.state = State.READY
            return "READY：已武装，按【十字上】开始录制"
        if self.state is State.READY:
            self.state = State.IDLE
            return "已取消待命"
        if self.state is State.RECORDING:
            self._abort()
            return "录制中止，数据已丢弃"
        if self.state is State.REVIEW:
            self.discard()
            return "已丢弃上一条"
        return ""

    def toggle_record(self) -> str:
        """十字上：开始 / 结束录制。"""
        if self.state is State.READY:
            self._begin()
            return "开始录制"
        if self.state is State.RECORDING:
            self._end()
            return "结束录制，等待判定"
        return ""

    def save(self) -> str:
        """十字左：保存当前 episode。"""
        if self.state is not State.REVIEW:
            return ""
        self.episode.success = True
        self.episode.finished_at = self.episode.finished_at or time.time()
        dest = "memory"
        if self._saver is not None:
            try:
                dest = self._saver(self.episode)
            except Exception as e:                       # noqa: BLE001
                self._emit("error", f"保存失败: {type(e).__name__}: {e}")
                return f"保存失败: {type(e).__name__}"
        self._saved.append(self.episode)
        n = self.episode.n_frames
        eid = self.episode.episode_id
        self._emit("save", f"episode {eid} 已保存 ({n} 帧) -> {dest}")
        self._reset_to_idle()
        return f"已保存 episode {eid}（{n} 帧）"

    def discard(self) -> str:
        """十字右：丢弃当前 episode。"""
        if self.state is not State.REVIEW:
            return ""
        eid = self.episode.episode_id
        n = self.episode.n_frames
        self.episode.success = False
        self._discarded += 1
        self._emit("discard", f"episode {eid} 已丢弃 ({n} 帧)")
        self._reset_to_idle()
        return f"已丢弃 episode {eid}（{n} 帧）"

    # ------------------------------------------------------------ 内部转移
    def _begin(self) -> None:
        self.episode = EpisodeBuffer(episode_id=self._next_id)
        self._next_id += 1
        self.episode.started_at = time.time()
        self.state = State.RECORDING

    def _end(self) -> None:
        self.episode.finished_at = time.time()
        self.state = State.REVIEW
        self._emit("review",
                   f"episode {self.episode.episode_id} 录完 "
                   f"({self.episode.n_frames} 帧, {self.episode.duration:.1f}s)")

    def _abort(self) -> None:
        self._discarded += 1
        self._reset_to_idle()

    def _reset_to_idle(self) -> None:
        self.episode = EpisodeBuffer(episode_id=self._next_id)
        self.state = State.IDLE

    # ---------------------------------------------------------------- 采集
    def capture(self, frame: dict) -> None:
        """在 RECORDING 状态下记录一帧。"""
        if self.state is not State.RECORDING:
            return
        if self._images_fn is not None:
            try:
                imgs = self._images_fn() or {}
                if imgs:
                    frame = dict(frame)
                    for k, v in imgs.items():
                        if v is not None:
                            frame["image_%s" % k] = v
                    # 兼容单图字段：默认用 head（相机资产自带的主视图）
                    main = imgs.get("head")
                    if main is None:
                        main = next((v for v in imgs.values() if v is not None),
                                    None)
                    if main is not None:
                        frame["image"] = main
            except Exception as e:                            # noqa: BLE001
                self._emit("error", f"取帧失败: {type(e).__name__}: {e}")
        elif self._image_fn is not None:
            try:
                img = self._image_fn()
                if img is not None:
                    frame = dict(frame)
                    frame["image"] = img
            except Exception as e:                            # noqa: BLE001
                self._emit("error", f"取帧失败: {type(e).__name__}: {e}")
        self.episode.append(frame)

    # ---------------------------------------------------------------- 统计
    @property
    def saved_episodes(self) -> list[EpisodeBuffer]:
        return list(self._saved)

    @property
    def n_saved(self) -> int:
        return len(self._saved)

    @property
    def n_discarded(self) -> int:
        return self._discarded

    # ---------------------------------------------------------------- 显示
    def status_line(self, fps: float = 0.0) -> str:
        """给控制台用的一行状态。"""
        if self.state is State.IDLE:
            return (f"[IDLE]    已保存 {self.n_saved} 条, 丢弃 {self.n_discarded} 条"
                    f"  | 十字下=待命")
        if self.state is State.READY:
            return "[READY]   已武装 | 十字上=开始 十字下=取消"
        if self.state is State.RECORDING:
            return (f"[REC]     ep{self.episode.episode_id} "
                    f"{self.episode.n_frames} 帧 | 十字上=结束 十字下=中止")
        return (f"[REVIEW]  ep{self.episode.episode_id} {self.episode.n_frames} 帧 "
                f"{self.episode.duration:.1f}s | 十字左=保存 十字右=丢弃")
