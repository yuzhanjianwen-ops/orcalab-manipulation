# -*- coding: utf-8 -*-
"""G1 三相机取图 —— 走 OrcaStudio 视口渲染（**实测可用**）。

为什么是这个方案
================
这台 G1 的三个相机（head / wrist_l / wrist_r）在场景里是**独立的相机 Actor**：

    /head_camera_1      -> 子实体 /camera  (640x480, FOV 50, ColorPort 7070)
    /wrist_camera_l     -> 子实体 /camera  (ColorPort 7080)
    /wrist_camera_r     -> 子实体 /camera  (ColorPort 7090)

实测结论（踩过的坑，别重复走）：
  * WebSocket 7070/7080/7090 —— 端口在监听但**不推流**；
    要推流必须仿真模型里有 MuJoCo `<camera>`（`ncam>0`），当前 `ncam=0`。
  * `SetCameraSensorInfo` / `MakeCameraViewportActive` —— 全部
    "Camera actor name not found"（因为 `ncam=0`）。
  * 50051 `GetCameraFramePNG` —— 返回空 `name_transform`（同样依赖 `ncam>0`）。
  * 往 `tmp/out.xml` 注入 `<camera>` —— 每次 `start_simulation` 都会被
    Studio 重新生成覆盖，**无效**。

**唯一可行**：50151 编辑服务切相机 + Studio 视口渲染落盘：
    1. 50151 `GetCameras()`                    -> 列出相机 (index/name/actor_path)
    2. 50151 `SetActiveCamera(index)`          -> 把视口切到目标相机
    3. MCP  `get_viewport_camera_info(index)`  -> 触发渲染一帧并落盘
    4. 读 `C:\\Users\\<user>\\.orcalab\\viewport_image\\color\\<cam>_color_<idx>.png`

用法：
    feed = ViewportCameraFeed(tags=("head", "wrist_l", "wrist_r"))
    feed.open()
    frames = feed.grab_multi()     # {"head": ndarray(H,W,3) BGR, ...}
    feed.close()
"""
from __future__ import annotations

import os
import sys
import json
import time
import threading

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 50151 编辑服务（OrcaStudio 编辑态 gRPC）
EDIT_ADDR = "127.0.0.1:50151"
# Studio 视口渲染落盘目录
VIEWPORT_DIR = os.path.join(os.path.expanduser("~"), ".orcalab", "viewport_image")

# 默认三相机：**机器人自带**（挂在 /dual_arm_collaborative_service_robot_1 上）
#
# 重要：这三个相机的 actor_path 完全相同（都是机器人本体），
# 所以**必须按相机名（c.name）匹配**，不能按 actor_path，否则会互相串。
#   名字            index   tag
#   camera_head       1     head
#   camera_left       2     left
#   camera_right      3     right
DEFAULT_TARGETS = (
    ("camera_head",  "head"),
    ("camera_left",  "left"),
    ("camera_right", "right"),
)


class ViewportCameraFeed:
    """从 OrcaStudio 视口渲染取 G1 三相机画面。

    注意：Studio 一次只能有**一个**激活相机，所以取三路要**轮流切**。
    每次 grab_multi() 会依次切到三个相机各渲染一帧。
    """

    def __init__(self, targets=None, edit_addr: str = EDIT_ADDR,
                 mcp_addr: str = "127.0.0.1:12345",
                 viewport_dir: str = VIEWPORT_DIR,
                 settle: float = 1.2, timeout: float = 15.0):
        self.targets = tuple(targets or DEFAULT_TARGETS)   # ((actor_path, tag), ...)
        self.edit_addr = edit_addr
        self.mcp_addr = mcp_addr
        self.viewport_dir = viewport_dir
        self.settle = settle          # 切相机后等渲染的秒数
        self.timeout = timeout

        self.ok = False
        self.error = ""
        self.channels: dict[str, int] = {}      # tag -> 相机 index
        self._stub = None
        self._ep = None
        self._mcp = None
        self._cv2 = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._latest: dict[str, np.ndarray] = {}
        self._idx = 0
        self.grab_fps = 0.0

    # ------------------------------------------------------------- 打开
    def open(self) -> bool:
        try:
            sys.path.insert(0, HERE)
            from orca_boot import redirect_report       # noqa: F401
            import grpc
            import orcalab.protos.edit_service_pb2 as ep
            import orcalab.protos.edit_service_pb2_grpc as epg
            import cv2
        except Exception as e:                          # noqa: BLE001
            self.error = "导入失败: %s: %s" % (type(e).__name__, e)
            return False
        try:
            from orca_mcp import OrcaMcp
        except Exception as e:                          # noqa: BLE001
            self.error = "导入 orca_mcp 失败: %s: %s" % (type(e).__name__, e)
            return False

        self._ep, self._cv2 = ep, cv2
        try:
            self._stub = epg.GrpcServiceStub(grpc.insecure_channel(self.edit_addr))
        except Exception as e:                          # noqa: BLE001
            self.error = "连 %s 失败: %s: %s" % (self.edit_addr, type(e).__name__, e)
            return False

        # 列相机，按 actor_path 匹配 index
        try:
            r = self._stub.GetCameras(ep.GetCamerasRequest(), timeout=self.timeout)
        except Exception as e:                          # noqa: BLE001
            self.error = "GetCameras 失败: %s: %s" % (type(e).__name__, e)
            return False

        by_actor = {}
        by_name = {}
        for c in r.cameras:
            if c.actor_path:
                by_actor.setdefault(c.actor_path, []).append(c.index)
            if c.name:
                by_name.setdefault(c.name, []).append(c.index)
        missing = []
        for key, tag in self.targets:
            # 先按相机名精确匹配（机器人自带三相机必需），
            # 匹配不到再回退按 actor 路径（兼容场景里独立相机）
            idxs = by_name.get(key) or by_actor.get(key)
            if not idxs:
                missing.append(key)
                continue
            if len(idxs) > 1 and key in by_name:
                # 同名多个：给出警告但仍取第一个
                print("[cam] [warn] 相机名 '%s' 有多个 index: %s，取 %d"
                      % (key, idxs, idxs[0]), flush=True)
            self.channels[tag] = idxs[0]
        if missing:
            self.error = "找不到相机: %s\n  当前 name: %s\n  当前 actor: %s" % (
                ", ".join(missing), ", ".join(sorted(by_name)),
                ", ".join(sorted(by_actor)))
            return False
        if not self.channels:
            self.error = "没有可用的相机"
            return False

        # 连 MCP（触发渲染用）
        try:
            self._mcp = OrcaMcp(timeout=int(self.timeout * 4))
            self._mcp.connect()
        except Exception as e:                          # noqa: BLE001
            self.error = "连 MCP(%s) 失败: %s: %s" % (self.mcp_addr, type(e).__name__, e)
            return False

        # 先抓一轮，确认通路
        first = self._grab_once()
        if not first or all(v is None for v in first.values()):
            self.error = "首帧抓取失败（视口渲染没出图）"
            return False
        with self._lock:
            self._latest = {k: v for k, v in first.items() if v is not None}

        self.ok = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    # ------------------------------------------------------------- 内部
    def _grab_once(self) -> dict:
        """轮流切三个相机，各渲染一帧，返回 {tag: ndarray|None}。"""
        from orca_mcp import call_text
        out = {}
        for tag, idx in self.channels.items():
            try:
                self._stub.SetActiveCamera(
                    self._ep.SetActiveCameraRequest(index=idx), timeout=self.timeout)
            except Exception:                           # noqa: BLE001
                out[tag] = None
                continue
            time.sleep(self.settle)
            try:
                payload = call_text(self._mcp, "get_viewport_camera_info", {"index": idx})
                d = json.loads(payload)
                cp = d.get("color_path", "")
            except Exception:                           # noqa: BLE001
                out[tag] = None
                continue
            out[tag] = self._read_png(cp)
        return out

    def _read_png(self, path: str):
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                buf = fh.read()
        except (FileNotFoundError, PermissionError, OSError):
            return None
        if not buf:
            return None
        arr = np.frombuffer(buf, dtype=np.uint8)
        return self._cv2.imdecode(arr, self._cv2.IMREAD_COLOR)

    def _loop(self) -> None:
        cnt, t0 = 0, time.time()
        while not self._stop.is_set():
            try:
                res = self._grab_once()
                if any(v is not None for v in res.values()):
                    with self._lock:
                        for k, v in res.items():
                            if v is not None:
                                self._latest[k] = v
                        self._idx += 1
                    cnt += 1
                    now = time.time()
                    if now - t0 >= 1.0:
                        self.grab_fps = cnt / (now - t0)
                        cnt, t0 = 0, now
            except Exception as e:                      # noqa: BLE001
                self.error = "取图线程: %s: %s" % (type(e).__name__, e)
                time.sleep(0.2)

    # ------------------------------------------------------------- 取帧
    def frame_size(self) -> tuple[int, int]:
        """返回首帧的 (H, W)；还没抓到帧时返回 (0, 0)。

        给 LeRobot 落盘器推导图像 feature 的真实尺寸用
        （LeRobot 默认 720x1280，与实际 1080x1080 不符会报错）。
        """
        with self._lock:
            for v in self._latest.values():
                if v is not None and getattr(v, "ndim", 0) == 3:
                    return int(v.shape[0]), int(v.shape[1])
        return (0, 0)

    def grab_multi(self) -> dict:
        """返回 {tag: ndarray(H,W,3) BGR}；未就绪的通道为 None。"""
        with self._lock:
            return {k: (None if v is None else v.copy())
                    for k, v in self._latest.items()}

    def grab(self):
        """兼容单图接口：返回第一个通道（默认 head）。"""
        d = self.grab_multi()
        for tag in [t for _, t in self.targets]:
            if d.get(tag) is not None:
                return d[tag]
        return None

    def close(self) -> None:
        self.ok = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._stub = None
        self._mcp = None


if __name__ == "__main__":
    feed = ViewportCameraFeed()
    print("打开相机 ...")
    if not feed.open():
        print("失败:", feed.error)
        sys.exit(1)
    print("通道:", feed.channels)
    time.sleep(3.0)
    frames = feed.grab_multi()
    print("取到通道:", {k: (None if v is None else v.shape) for k, v in frames.items()})
    outdir = os.path.join(HERE, "out_final")
    os.makedirs(outdir, exist_ok=True)
    for tag, img in frames.items():
        if img is not None:
            fp = os.path.join(outdir, "multi_%s.png" % tag)
            feed._cv2.imwrite(fp, img)
            print("  saved", fp)
    feed.close()
