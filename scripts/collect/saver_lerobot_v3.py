# -*- coding: utf-8 -*-
"""LeRobot v3.0 落盘器（给 collect.py 用，与 Hdf5Saver 接口一致）。

背景
====
以前只能存 HDF5（甲方 OrcaManipulation 也是 HDF5），训练侧还要写转换脚本。
现在这个落盘器让 **采集按键一按，直接产出标准 LeRobot v3.0 数据集**，
目录结构与 lerobot 官方 LeRobotDataset.create() 完全一致，可直接拿去训练。

它怎么工作
----------
collect.py 的采集模型是「先全存内存、按键判定后再落盘」（Recorder.set_saver 注入点）。
所以本模块在 save() 时把内存里攒好的一整条 episode **一次交给 LeRobot**：
add_frame 逐帧喂 -> save_episode 编码视频。

字段映射（本项目的每帧 dict -> LeRobot feature）
------------------------------------------------
    observation.state          <- joint_pos(14) + gripper_pos(16) + ee_pos(6) + ee_quat(8) = 44
    action                     <- 活动臂末端目标 pos(3) + quat(4) + gripper(1) = 8
    observation.images.head    <- image_head    (相机 camera_head)
    observation.images.left    <- image_left    (相机 camera_left)
    observation.images.right   <- image_right   (相机 camera_right)

图像必须是 RGB。orca_gym 的 CameraRecorder.decode_frame_at / last_decoded_frame
返回的就是 RGB（见 camera_recorder.py 的 to_ndarray(format="rgb24")），
LeRobot 写视频时也会 convert("RGB")，所以喂 RGB 是正确顺序；塞 BGR 会红蓝互换。

Windows 上必须注意的两点
------------------------
1. save_episode(parallel_encoding=False) —— 进程池在 Windows 下会崩。
2. 脚本必须有 if __name__ == "__main__" 保护，否则 spawn 子进程会重复导入主模块。

依赖
----
    pip install "lerobot[dataset]>=0.6.1" pyarrow av
    # av 必须 >=15,<16（PyAV 16+ 与 lerobot 0.6.x 不兼容）
"""
from __future__ import annotations

import io
import json
import os
from typing import Optional

import numpy as np

# ---------------------------------------------------------------- 向量布局
STATE_NAMES: list[str] = (
    ["joint_pos_%d" % i for i in range(14)]
    + ["gripper_pos_%d" % i for i in range(16)]
    + ["ee_pos_%d" % i for i in range(6)]
    + ["ee_quat_%d" % i for i in range(8)]
)
ACTION_NAMES: list[str] = (
    ["action_pos_%d" % i for i in range(3)]
    + ["action_quat_%d" % i for i in range(4)]
    + ["action_gripper"]
)
STATE_DIM = len(STATE_NAMES)        # 44
ACTION_DIM = len(ACTION_NAMES)      # 8

# 每帧 dict 里的图像键 -> LeRobot 相机名（与 collect.py --cam3 的 tag 对齐）
DEFAULT_CAMERAS = (("head", "image_head"),
                   ("left", "image_left"),
                   ("right", "image_right"))


# ---------------------------------------------------------------- 导入
def _import_lerobot():
    """动态导入 LeRobotDataset，兼容新旧模块路径。"""
    import importlib

    for mod in ("lerobot.datasets.lerobot_dataset",
                "lerobot.common.datasets.lerobot_dataset"):
        try:
            return importlib.import_module(mod).LeRobotDataset
        except ImportError:
            continue
    raise ImportError(
        "无法导入 LeRobotDataset：当前环境缺 lerobot。请执行：\n"
        '    & "<你的python.exe>" -m pip install "lerobot[dataset]>=0.6.1" pyarrow av\n'
        "不需要 LeRobot 格式时，可继续用 HDF5（saver_hdf5.py）。")


def lerobot_available() -> tuple[bool, str]:
    """探测 lerobot 是否可用，返回 (是否可用, 说明)。"""
    try:
        _import_lerobot()
    except ImportError as e:
        return False, str(e)
    except Exception as e:                                   # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)
    return True, "ok"


# ---------------------------------------------------------------- 向量组装
def _state_vector(frame: dict) -> Optional[np.ndarray]:
    """从一帧 dict 拼出 observation.state（44 维）。缺字段返回 None。"""
    try:
        return np.concatenate([
            np.asarray(frame["joint_pos"], dtype=np.float32).reshape(-1),
            np.asarray(frame["gripper_pos"], dtype=np.float32).reshape(-1),
            np.asarray(frame["ee_pos"], dtype=np.float32).reshape(-1),
            np.asarray(frame["ee_quat"], dtype=np.float32).reshape(-1),
        ]).astype(np.float32)
    except (KeyError, ValueError):
        return None


def _action_vector(frame: dict) -> Optional[np.ndarray]:
    """从一帧 dict 拼出 action（8 维）。缺 pos/quat 返回 None。"""
    pos = frame.get("action_pos")
    quat = frame.get("action_quat")
    if pos is None or quat is None:
        return None
    grip = frame.get("action_gripper")
    pos = np.asarray(pos, dtype=np.float32).reshape(3)
    quat = np.asarray(quat, dtype=np.float32).reshape(4)
    g = np.float32(0.0) if grip is None else np.float32(grip)
    return np.concatenate([pos, quat, [g]]).astype(np.float32)


# ---------------------------------------------------------------- 落盘器
class LeRobotSaver:
    """把 EpisodeBuffer 存成 LeRobot v3.0 数据集。

    与 Hdf5Saver 接口一致（__call__(episode) -> str），
    可直接塞进 Recorder.set_saver()。

    Parameters
    ----------
    root : str
        数据集根目录（**必须是专用子目录**，非 resume 模式 LeRobot 会先清空它）。
    repo_id : str
        LeRobot 数据集标识，默认 local/dual_arm_teleop。
    fps : int
        采集帧率，写进 meta（训练侧按它算时间戳）。
    robot_type : str
        机器人型号标识（写进 meta）。
    task : str
        任务语言描述（写进 meta，训练时做 task-conditioning）。
    cameras : dict | None
        {"head": {"height": H, "width": W}, ...}；None 表示无图像。
        一般由 collect.py 从相机 frame_size() 自动推导。
    resume : bool
        True 则追加到已有数据集（第二场采集接着上一场写）。
    use_videos : bool
        True 用 mp4 视频（推荐，省空间）；False 用 parquet 内嵌 PNG。
    """

    def __init__(self, root: str, repo_id: str = "local/dual_arm_teleop",
                 fps: int = 20, robot_type: str = "dual_arm_service_robot",
                 task: str = "teleop", cameras: Optional[dict] = None,
                 resume: bool = False, use_videos: bool = True,
                 metadata_buffer_size: int = 1, verbose: bool = True,
                 require_cameras: bool = True):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.repo_id = repo_id
        self.fps = int(fps)
        self.robot_type = robot_type
        self.task = task
        self.cameras = dict(cameras or {})
        self.resume = bool(resume)
        # 默认要求至少一路相机：采集脚本期望有图像，
        # 一旦接不到帧就应该明报错，而不是静默地
        # 写出一个没有图像的数据集。
        self.require_cameras = bool(require_cameras)
        self.use_videos = bool(use_videos)
        # lerobot 默认攒够 10 集才写一次 meta/episodes；录 1 集就崩溃 -> 元数据全丢。
        # 设为 1 = 每集保存后立刻落盘。
        self.metadata_buffer_size = max(1, int(metadata_buffer_size))
        self.verbose = bool(verbose)

        self.saved: list[str] = []
        self._dataset = None
        self._episodes_written = 0
        self._frames_written = 0

    # ------------------------------------------------------------ 小工具
    def _log(self, msg: str) -> None:
        if self.verbose:
            print("[LeRobot] " + msg, flush=True)

    def _dir_is_empty(self, path: str) -> bool:
        if not os.path.isdir(path):
            return False
        try:
            return len(os.listdir(path)) == 0
        except OSError:
            return False

    def _validate_root(self) -> None:
        """拒绝危险的 root（非 resume 模式下 LeRobot 会 rmtree 它）。"""
        root = self.root
        cwd = os.path.abspath(os.getcwd())
        home = os.path.abspath(os.path.expanduser("~"))
        if root in ("", ".", os.sep):
            raise ValueError(
                "LeRobot root 为空或指向当前目录。请用 --lerobot-out 指定专用子目录。")
        if root == cwd:
            raise ValueError(
                "LeRobot root 是当前工作目录（%s），非 resume 模式下会被清空，"
                "可能删掉源码。请改用专用子目录。" % root)
        if root == home:
            raise ValueError("LeRobot root 指向用户 home，请改用专用子目录。")

    # ------------------------------------------------------------ features
    def _features(self, dims: tuple[int, int]) -> dict:
        """按每路相机的**真实帧尺寸**生成 feature。

        重要（历史 bug）
        ----------------
        旧实现写的是 `first.get("height", 480)` —— 带默认值。一旦 cameras
        没探测到（或探测错），就会悄悄退回默认值，甚至退到 LeRobot 内部的
        720x1280，最终与真实帧不符、保存报错。
        现在完全去掉默认值：每路相机必须有它自己的 (h, w)，否则直接抛错，
        绝不“猜一个尺寸”。
        """
        state_dim, action_dim = dims
        state_names = (STATE_NAMES if state_dim == STATE_DIM else None)
        action_names = (ACTION_NAMES if action_dim == ACTION_DIM else None)
        feats = {
            "observation.state": {"dtype": "float32", "shape": (state_dim,),
                                  "names": state_names},
            "action": {"dtype": "float32", "shape": (action_dim,),
                       "names": action_names},
        }
        for name, spec in self.cameras.items():
            h = spec.get("height")
            w = spec.get("width")
            if not h or not w:
                raise RuntimeError(
                    "相机 '%s' 没有真实帧尺寸（cameras['%s']=%r）。"
                    "本落盘器拒绝用默认尺寸，请检查相机是否接到帧。"
                    % (name, name, spec))
            # 每路相机独立记录自己的尺寸，不假设三路一致
            feats["observation.images.%s" % name] = {
                "dtype": "video" if self.use_videos else "image",
                "shape": (3, int(h), int(w)),
                "names": ["channels", "height", "width"],
            }
        return feats

    # ------------------------------------------------------------ 探维度
    def peek_dims(self, episode) -> tuple[int, int]:
        """从 episode 首帧推出 (state_dim, action_dim)，用于创建数据集。"""
        data = episode.stacked()
        n = episode.n_frames
        rep = {k: v[0] for k, v in data.items() if len(v) == n}
        st = _state_vector(rep)
        act = _action_vector(rep)
        state_dim = int(st.shape[0]) if st is not None else STATE_DIM
        action_dim = int(act.shape[0]) if act is not None else ACTION_DIM
        return state_dim, action_dim

    def peek_cameras(self, episode, strict: bool = False) -> dict:
        """从 episode 里**逐帧扫描**推出每路相机的真实 (height, width)。

        为什么要逐帧扫，而不是只看第 0 帧
        ----------------------------------
        首帧可能是占位图 / 尺寸尚未稳定的一帧。逐帧扫能同时拿到：
          * 该相机真实出现的**最小/最大**尺寸
          * 若同一集内尺寸发生变化（不该发生）能立刻发现并报错

        strict=True 时，若某路相机完全没有可用帧，直接抛错（保存路径用）；
        strict=False 时静默跳过（自检/预览路径用）。
        """
        data = episode.stacked()
        n = episode.n_frames
        cams = {}
        for name, key in DEFAULT_CAMERAS:
            arr = data.get(key)
            if arr is None or len(arr) == 0:
                if strict:
                    raise RuntimeError(
                        "相机 '%s'（帧字段 '%s'）在本次 episode 里没有任何帧。"
                        "请确认 --cam3-ws 已接上该相机。" % (name, key))
                continue
            shapes = {}
            for i in range(len(arr)):
                img = np.asarray(arr[i])
                if img.ndim != 3:
                    continue
                shapes[(int(img.shape[0]), int(img.shape[1]))] = \
                    shapes.get((int(img.shape[0]), int(img.shape[1])), 0) + 1
            if not shapes:
                if strict:
                    raise RuntimeError(
                        "相机 '%s' 的帧都不是 3 维图像（H,W,C）。" % name)
                continue
            if len(shapes) > 1:
                # 同一集内出现多种尺寸 —— 必须报错，不能挑一个
                detail = ", ".join("%dx%d x%d帧" % (h, w, c)
                                   for (h, w), c in sorted(shapes.items()))
                raise RuntimeError(
                    "相机 '%s' 在同一个 episode 内出现了多种尺寸：%s。"
                    "这通常意味着相机中途重连/改分辨率。请录一条尺寸稳定的数据。"
                    % (name, detail))
            (h, w), cnt = next(iter(shapes.items()))
            cams[name] = {"height": h, "width": w, "frames": cnt}
        if strict and not cams:
            raise RuntimeError(
                "本 episode 里一路相机都没接到帧，无法生成图像 feature。")
        return cams

    # ------------------------------------------------------------ 数据集
    def _ensure_dataset(self, dims: tuple[int, int]):
        """首次保存时创建（或恢复）LeRobotDataset。"""
        if self._dataset is not None:
            return self._dataset
        self._validate_root()
        LeRobotDataset = _import_lerobot()

        if self.resume and os.path.isdir(self.root) \
                and os.path.exists(os.path.join(self.root, "meta", "info.json")):
            self._log("resume 已有数据集: %s" % self.root)
            self._dataset = LeRobotDataset.resume(
                repo_id=self.repo_id, root=self.root,
                video_backend="pyav", image_writer_threads=0)
            return self._dataset

        # 非 resume：处理「目录已存在」
        if os.path.isdir(self.root):
            if self._dir_is_empty(self.root):
                try:
                    os.rmdir(self.root)
                    self._log("清理上次失败留下的空目录: %s" % self.root)
                except OSError as e:
                    raise RuntimeError(
                        "输出目录已存在且为空，但无法删除: %s\n  原因: %s\n"
                        "  请手动删除后重试，或改用其它目录。" % (self.root, e)) from e
            else:
                raise RuntimeError(
                    "输出目录已存在且**非空**，为防误删已拒绝覆盖:\n  %s\n"
                    "  想追加到该数据集 -> 加 --resume\n"
                    "  想重新采集       -> 先手动清空/删除该目录\n"
                    "  （在采集脚本里删目录很容易删错，所以故意不自动删）"
                    % self.root)

        feats = self._features(dims)
        self._log("创建数据集: %s" % self.root)
        self._log("  fps=%d videos=%s features=%s"
                  % (self.fps, self.use_videos, list(feats)))
        try:
            self._dataset = LeRobotDataset.create(
                repo_id=self.repo_id,
                fps=self.fps,
                features=feats,
                root=self.root,
                robot_type=self.robot_type,
                use_videos=self.use_videos,
                image_writer_processes=0,     # Windows 下进程池会崩
                image_writer_threads=0,
                metadata_buffer_size=self.metadata_buffer_size,
            )
        except Exception:
            # create() 失败会留下空目录，把下一次保存的 FileExistsError
            # 盖住真实错误 —— 这里回滚空目录，保留真实 traceback。
            self._rollback_empty_dir()
            raise
        return self._dataset


    def _rollback_empty_dir(self) -> None:
        try:
            if self._dir_is_empty(self.root):
                os.rmdir(self.root)
                self._log("已回滚 create() 留下的空目录: %s" % self.root)
        except OSError:
            pass

    # ------------------------------------------------------------ 主入口
    def __call__(self, episode) -> str:
        """把一集存成 LeRobot 数据集。

        形状策略（以真实帧为准）
        ------------------------
        * 每集保存前，**重新**从本集真实帧探测每路相机的 (h, w)；
        * 首次建数据集时用该尺寸，之后每集都校验与已注册尺寸是否一致；
        * 逐帧校验：一旦某帧尺寸与注册尺寸不符，立刻报错并指出
          「第几帧、哪路相机、实际多少、期望多少」，绝不静默写入。
        这样无论相机输出 480x640 还是 1280x720，都以实际收到的帧为准。
        """
        data = episode.stacked()
        n = episode.n_frames
        if n == 0:
            raise RuntimeError("episode 是空的，没有可保存的帧")

        dims = self.peek_dims(episode)

        # —— 关键：永远以本集真实帧为准 ——
        cams = self.peek_cameras(episode, strict=False)
        if cams:
            real = {k: {"height": v["height"], "width": v["width"]}
                    for k, v in cams.items()}
            if not self.cameras:
                self.cameras = real
                self._log("相机真实尺寸: %s" % ", ".join(
                    "%s=%dx%d" % (k, v["height"], v["width"])
                    for k, v in sorted(real.items())))
            else:
                # 已建过数据集：校验尺寸没变（变了会写坏视频）
                for k, v in real.items():
                    cur = self.cameras.get(k)
                    if cur is None:
                        # 本集多了一路此前没见过的相机
                        raise RuntimeError(
                            "本集出现了数据集里没有的相机 '%s'。"
                            "请新建数据集（去掉 --lerobot-resume）。" % k)
                    if (int(cur.get("height")) != v["height"]
                            or int(cur.get("width")) != v["width"]):
                        raise RuntimeError(
                            "相机 '%s' 尺寸变了：数据集注册的是 %sx%s，"
                            "本集真实帧是 %dx%d。\n"
                            "  LeRobot 不允许同一数据集内分辨率变化。\n"
                            "  -> 请去掉 --lerobot-resume，新建一个数据集目录。"
                            % (k, cur.get("height"), cur.get("width"),
                               v["height"], v["width"]))
                for k in self.cameras:
                    if k not in real:
                        raise RuntimeError(
                            "数据集注册了相机 '%s'，但本集没有它的帧。"
                            "请检查相机连接。" % k)
        elif self.cameras or self.require_cameras:
            # 本次没接到图，但数据集是要图的 —— 明确报错，不要写出坏数据
            raise RuntimeError(
                u"本次 episode 一帧图像都没收到（已注册相机：%s）。\n"
                "相机没推流 / --cam3-ws 未接上 / 帧里缺 image_* 字段。"
                % (sorted(self.cameras) or u"无（首次即未探测到）",))

        ds = self._ensure_dataset(dims)

        # 注册尺寸（来自真实帧）
        expect = {k: (int(v["height"]), int(v["width"]))
                  for k, v in self.cameras.items()}

        img_keys = [k for k in self.cameras if ("image_%s" % k) in data]
        written = 0
        checked = 0
        for i in range(n):
            frame = {k: v[i] for k, v in data.items() if len(v) == n}
            state = _state_vector(frame)
            if state is None:
                continue
            action = _action_vector(frame)
            item = {
                "observation.state": state,
                # action 缺字段时退化为 state 前 N 维（保证形状一致，不丢帧）
                "action": action if action is not None
                          else state[:dims[1]].astype(np.float32),
                "task": self.task,
            }
            for k in img_keys:
                img = np.asarray(data["image_%s" % k][i])
                if img.ndim != 3:
                    continue
                eh, ew = expect[k]
                ah, aw = int(img.shape[0]), int(img.shape[1])
                if (ah, aw) != (eh, ew):
                    raise RuntimeError(
                        "第 %d 帧的相机 '%s' 尺寸是 %dx%d，"
                        "但数据集注册的是 %dx%d —— 拒绝写入形状不一致的帧。"
                        "（视频编码一旦混入不同尺寸就会写坏）"
                        % (i, k, ah, aw, eh, ew))
                checked += 1
                item["observation.images.%s" % k] = img
            ds.add_frame(item)
            written += 1

        if written == 0:
            raise RuntimeError("episode 无有效帧（缺 joint_pos/ee_pos 等字段）")

        # Windows：必须关掉并行编码（进程池会崩）
        ds.save_episode(parallel_encoding=False)
        # 关键：立即写入 parquet footer，
        # 保证数据在会话进行中就可读，崩溃也不丢。
        self._make_durable()
        self._flush_episode()

        self._episodes_written += 1
        self._frames_written += written
        self.saved.append(self.root)
        return "%s (ep %d, %d 帧)%s" % (self.root, episode.episode_id,
                                        written, self._action_stats())

    # ------------------------------------------------------------ 落盘
    def _make_durable(self) -> None:
        u"""每存完一集就把 parquet footer 刷到磁盘，让数据**立刻可读**。

        为什么必须做
        ----------------
        lerobot 的 ParquetWriter 一直保持打开，只在
        finalize()/close() 时才把 footer 写入。这意味着：

          * 会话进行中，data/*.parquet 与
            meta/episodes/*.parquet 都是“没有 footer 的半成品”，
            pyarrow 直接报 ArrowInvalid: Parquet magic bytes
            not found in footer。
          * 进程崩溃/强杀 → 刚采的几集全部丢失。
          * --resume 中途接上会失败，因为上一次的
            元数据读不出来。

        为什么这样做是安全的
        ----------------------
        两个 writer 都是 **lazy append** 设计：_pq_writer 为 None
        时下次写会重新打开同一路径继续追写。
        这里只关 footer，不动累计缓冲，也不调 finalize()
        （finalize 会释放 image_writer，会话还没结束，不能关）。
        u"""
        ds = self._dataset
        if ds is None:
            return
        writer = getattr(ds, "writer", None)
        if writer is not None:
            fn = getattr(writer, "close_writer", None)
            if callable(fn):
                try:
                    fn()
                except Exception as e:                        # noqa: BLE001
                    self._log("[warn] data parquet footer 刷盘失败: %s: %s"
                              % (type(e).__name__, e))
        meta = getattr(ds, "meta", None)
        if meta is not None:
            fn = getattr(meta, "_close_writer", None)
            if callable(fn):
                try:
                    fn()
                except Exception as e:                        # noqa: BLE001
                    self._log("[warn] meta parquet footer 刷盘失败: %s: %s"
                              % (type(e).__name__, e))

    # ------------------------------------------------------------ 统计
    def _action_stats(self) -> str:
        try:
            total_ep = int(self._dataset.meta.total_episodes)
            total_fr = int(self._dataset.meta.total_frames)
            return "  数据集共 %d 集 / %d 帧" % (total_ep, total_fr)
        except Exception:                                    # noqa: BLE001
            return ""

    def _flush_episode(self) -> None:
        """每集存完立刻把 meta/episodes 刷到磁盘。

        为什么需要
        ----------
        lerobot 默认 metadata_buffer_size=10：meta/episodes 攒满 10 集才写一次。
        中途崩溃/断电/被杀 -> 已录的集全部读不出来（meta/episodes 缺失，
        lerobot 会转去找 HuggingFace 报 401）。

        这里只刷 meta buffer（**不**调 finalize，也**不**关 parquet writer）：
        parquet 的 footer 统一交给 close()/finalize() 收尾，中途 close 反而
        会把同一个 file-000.parquet 写坏（实测 ArrowInvalid）。
        """
        ds = self._dataset
        if ds is None:
            return
        meta = getattr(ds, "meta", None)
        flush = getattr(meta, "_flush_metadata_buffer", None)
        if callable(flush):
            try:
                flush()
            except Exception as e:                           # noqa: BLE001
                self._log("[warn] flush metadata 失败: %s: %s"
                          % (type(e).__name__, e))

    @property
    def n_saved(self) -> int:
        return self._episodes_written

    @property
    def n_frames(self) -> int:
        return self._frames_written

    # ------------------------------------------------------------ 收尾
    def close(self) -> None:
        """写 parquet footer 并释放。不调用会导致 parquet 缺 footer 无法读取。"""
        if self._dataset is None:
            return
        for name in ("finalize", "stop_image_writer"):
            fn = getattr(self._dataset, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:                            # noqa: BLE001
                    pass
        if self.verbose:
            self._log("已收尾: %d 集 / %d 帧 -> %s"
                      % (self._episodes_written, self._frames_written, self.root))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __del__(self):
        try:
            if getattr(self, "_dataset", None) is not None:
                self.close()
        except Exception:                                    # noqa: BLE001
            pass
