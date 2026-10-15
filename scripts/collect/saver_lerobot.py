# -*- coding: utf-8 -*-
"""LeRobot v3.0 落盘（parquet + 视频）。

参考甲方 ``OrcaManipulation/src/dataStorage/lerobot_data_storage.py`` 的
``LeRobotDatasetWriter`` 设计，但**适配我们自己的采集链路**：

甲方做法（供对照）
------------------
* storage 层直接用 ``LeRobotDataset.create()``，相机走 OrcaGym 客户端 PyAV
  录制 + ``SingleFrameTask`` 逐帧 future 同步，**流式** ``add_frame``。
* 视频由 LeRobot 内部 ffmpeg 编码（``streaming_encoding=True``）。

我们的做法（本模块）
--------------------
我们的 ``Recorder`` 是"**先全存内存、按键判定后再落盘**"的模型
（``set_saver`` 注入点），和甲方"边采边写"不同。因此本模块：

* 在 ``save()`` 时把内存里攒好的一整条 episode **一次交给 LeRobot**；
* 仍用 ``LeRobotDataset`` 的官方 API（``create`` / ``add_frame`` /
  ``save_episode``），保证产出的目录结构与 LeRobot 3.0 完全一致，
  **可直接用于 lerobot 训练**；
* 图像按帧 ``add_frame`` 传入真实 RGB（若相机可用），由 LeRobot 编码成 MP4。

产出结构（标准 LeRobot 数据集）::

    <root>/
        data/     chunk-000/*.parquet
        videos/   observation.images.<cam>/chunk-000/*.mp4
        meta/     info.json  stats.json  tasks.parquet
              episodes/chunk-000/file-000.parquet

字段映射
--------
我们的每帧 dict（fields.py） -> LeRobot feature：

    observation.state    <- 关节+夹爪+末端位姿 拼成的固定维向量
    action               <- 末端目标位姿 + 夹爪指令 拼成的固定维向量
    observation.images.<cam>  <- 相机 RGB（可选）

依赖
----
    pip install "lerobot[dataset]>=0.6.1" pyarrow
    # 注意：av 必须 <16（>=15.0.0,<16），PyAV 16+ 与 lerobot 0.6.1 不兼容

缺失 lerobot 时**不报错退出**，而是抛出带安装提示的 ImportError，
由调用方决定是否降级到 HDF5。
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np

# 本项目的状态/动作向量布局（写进 LeRobot meta 的 names 字段）
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

STATE_DIM = len(STATE_NAMES)      # 44
ACTION_DIM = len(ACTION_NAMES)    # 8


# ------------------------------------------------------------------ 导入
def _import_lerobot():
    """动态导入 LeRobotDataset，兼容新旧模块路径。"""
    import importlib

    for mod in (
        "lerobot.datasets.lerobot_dataset",
        "lerobot.common.datasets.lerobot_dataset",
    ):
        try:
            return importlib.import_module(mod).LeRobotDataset
        except ImportError:
            continue
    raise ImportError(
        "无法导入 LeRobotDataset。当前环境缺失 lerobot 库，"
        "请执行：\n"
        '    & "<你的python.exe>" -m pip install "lerobot[dataset]>=0.6.1" pyarrow\n'
        "如不需要 LeRobot 格式，可改用 HDF5 落盘（saver_hdf5.py）。"
    )


def lerobot_available() -> tuple[bool, str]:
    """探测 lerobot 是否可用，返回 (是否可用, 说明)。"""
    try:
        _import_lerobot()
    except ImportError as e:
        return False, str(e)
    except Exception as e:                                   # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)
    return True, "ok"


# ------------------------------------------------------------------ 组装
def _state_vector(frame: dict) -> Optional[np.ndarray]:
    """从一帧 dict 拼出 observation.state（44 维）。"""
    try:
        return np.concatenate([
            np.asarray(frame["joint_pos"], dtype=np.float32),
            np.asarray(frame["gripper_pos"], dtype=np.float32),
            np.asarray(frame["ee_pos"], dtype=np.float32),
            np.asarray(frame["ee_quat"], dtype=np.float32),
        ]).astype(np.float32)
    except (KeyError, ValueError):
        return None


def _action_vector(frame: dict) -> Optional[np.ndarray]:
    """从一帧 dict 拼出 action（8 维）。缺字段时用零补齐。"""
    pos = frame.get("action_pos")
    quat = frame.get("action_quat")
    grip = frame.get("action_gripper")
    if pos is None or quat is None:
        return None
    pos = np.asarray(pos, dtype=np.float32).reshape(3)
    quat = np.asarray(quat, dtype=np.float32).reshape(4)
    g = np.float32(0.0) if grip is None else np.float32(grip)
    return np.concatenate([pos, quat, [g]]).astype(np.float32)


# ------------------------------------------------------------------ Saver
class LeRobotSaver:
    """把 EpisodeBuffer 存成 LeRobot v3.0 数据集。

    与 ``Hdf5Saver`` 接口一致（``__call__(episode) -> str``），
    因此可以直接塞进 ``Recorder.set_saver()``。

    Parameters
    ----------
    root : str
        数据集根目录（**必须是一个专用子目录**，不要用 ``.`` 或 home，
        因为 LeRobot 在非 resume 模式会先清空该目录）。
    repo_id : str
        LeRobot 数据集标识，默认 ``local/manipulation``。
    fps : int
        采集帧率，写入 meta。
    robot_type : str
        机器人型号标识（写入 meta）。
    task : str
        任务语言描述（写入 meta，训练时用）。
    cameras : dict | None
        ``{相机名: {"height": H, "width": W}}``；为 None 表示无图像。
    resume : bool
        True 则追加到已有数据集。
    """

    def __init__(self, root: str, repo_id: str = "local/manipulation",
                 fps: int = 20, robot_type: str = "dual_arm",
                 task: str = "teleop", cameras: Optional[dict] = None,
                 resume: bool = False, metadata_buffer_size: int = 1):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.repo_id = repo_id
        self.fps = int(fps)
        self.robot_type = robot_type
        self.task = task
        self.cameras = dict(cameras or {})
        self.resume = bool(resume)
        # meta/episodes 的落盘时机：lerobot 默认攒够 10 集才写一次，
        # 意味着录了 1 集就崩溃/断电 -> 该集元数据全丢，数据集读不出来。
        # 设为 1 = 每集保存后立刻落盘（甲方的做法也是每集写 footer）。
        self.metadata_buffer_size = max(1, int(metadata_buffer_size))

        self.saved: list[str] = []
        self._dataset = None
        self._warned_no_image = False

    # ------------------------------------------------------------ 校验
    def _validate_root(self) -> None:
        """拒绝危险的 root（LeRobot 会 rmtree 它）。"""
        root = self.root
        cwd = os.path.abspath(os.getcwd())
        home = os.path.abspath(os.path.expanduser("~"))
        if root in ("", ".", os.sep):
            raise ValueError(
                "LeRobot root 为空或为当前目录。请用 --lerobot-out 指定"
                "一个专用子目录（如 ./lerobot_out/my_dataset）。")
        if root == cwd:
            raise ValueError(
                "LeRobot root 是当前工作目录本身（%s），非 resume 模式下"
                "会被清空，可能删掉源码。请改用专用子目录。" % root)
        if root == home:
            raise ValueError("LeRobot root 指向用户 home，请改用专用子目录。")

    # ------------------------------------------------------------ 数据集
    def _features(self) -> dict:
        feats = {
            "observation.state": {
                "dtype": "float32",
                "shape": (STATE_DIM,),
                "names": [STATE_NAMES],
            },
            "action": {
                "dtype": "float32",
                "shape": (ACTION_DIM,),
                "names": [ACTION_NAMES],
            },
        }
        if self.cameras:
            first = next(iter(self.cameras.values()))
            shape = (3, int(first.get("height", 720)),
                     int(first.get("width", 1280)))
            for name in self.cameras:
                feats["observation.images.%s" % name] = {
                    "dtype": "video",
                    "shape": shape,
                    "names": ["channels", "height", "width"],
                }
        return feats

    def _dir_is_empty(self, path: str) -> bool:
        """判断目录是否存在且完全为空（没有任何文件/子目录）。"""
        if not os.path.isdir(path):
            return False
        try:
            return len(os.listdir(path)) == 0
        except OSError:
            return False

    def _ensure_dataset(self):
        """首次保存时创建（或恢复）LeRobotDataset。

        目录处理策略（避免 FileExistsError 把真实错误盖住）
        ---------------------------------------------------
        LeRobotDataset.create() 内部是 `mkdir(exist_ok=False)`，
        目标目录只要已存在就抛 FileExistsError。而一旦 create() 中途
        失败，它会留下一个**空目录**，导致**下一次**保存报
        FileExistsError —— 把第一次的真实错误彻底掩盖。

        因此这里：
          * resume 模式          -> 直接 resume 已有目录
          * 非 resume + 目录为空 -> 先清掉空目录再 create（安全，无数据）
          * 非 resume + 目录非空 -> 拒绝，提示加 --resume 或换目录（防误删）
          * create() 抛异常      -> 回滚本次留下的空目录，并抛出带完整
                                   traceback 的错误，绝不吞掉根因
        """
        if self._dataset is not None:
            return self._dataset
        self._validate_root()
        LeRobotDataset = _import_lerobot()

        kwargs = dict(repo_id=self.repo_id, root=self.root)

        if self.resume and os.path.isdir(self.root):
            self._dataset = LeRobotDataset.resume(**kwargs)
            return self._dataset

        # 非 resume：处理"目录已存在"的两种情况
        if os.path.isdir(self.root):
            if self._dir_is_empty(self.root):
                # 空目录 = 上次失败留下的残骸，清掉重来（无数据可丢）
                try:
                    os.rmdir(self.root)
                    print("[LeRobot] 清理上次残留的空目录: %s" % self.root)
                except OSError as e:
                    raise RuntimeError(
                        "输出目录已存在且为空，但无法删除: %s\n"
                        "  原因: %s\n"
                        "  请手动删除后重试，或改用其它 --lerobot-out。"
                        % (self.root, e)) from e
            else:
                raise RuntimeError(
                    "输出目录已存在且**非空**，为防误删已拒绝覆盖:\n"
                    "  %s\n"
                    "  若想追加到该数据集，请加 --resume；\n"
                    "  若想重新采集，请先手动清空/删除该目录。"
                    % self.root)

        try:
            self._dataset = LeRobotDataset.create(
                repo_id=self.repo_id,
                fps=self.fps,
                robot_type=self.robot_type,
                features=self._features(),
                root=self.root,
                use_videos=bool(self.cameras),
                # =1 -> 每集结束立即 flush meta/episodes，不等攒满 10 集
                metadata_buffer_size=self.metadata_buffer_size,
            )
        except Exception as e:
            # 回滚：create() 可能已建出目录/半成品，清掉以免污染下次运行
            import traceback as _tb
            detail = _tb.format_exc()
            self._rollback_partial_root()
            raise RuntimeError(
                "LeRobotDataset.create() 失败（原始错误未被掩盖）:\n"
                "  %s: %s\n"
                "输出目录: %s\n"
                "完整堆栈:\n%s"
                % (type(e).__name__, e, self.root, detail)) from e
        return self._dataset

    def _rollback_partial_root(self) -> None:
        """create() 失败后清掉它可能留下的空目录（有残留文件则保留并提示）。"""
        if not os.path.isdir(self.root):
            return
        try:
            if self._dir_is_empty(self.root):
                os.rmdir(self.root)
                print("[LeRobot] 已回滚 create() 留下的空目录: %s" % self.root)
            else:
                print("[LeRobot] [warn] create() 失败但目录非空，已保留以便排查: %s"
                      % self.root)
        except OSError as e:
            print("[LeRobot] [warn] 回滚空目录失败: %s" % e)

    # ------------------------------------------------------------ 主入口
    def __call__(self, episode) -> str:
        ds = self._ensure_dataset()
        data = episode.stacked()

        n = episode.n_frames
        img_keys = [k for k in self.cameras if k in data]

        written = 0
        for i in range(n):
            frame = {k: v[i] for k, v in data.items() if len(v) == n}
            state = _state_vector(frame)
            action = _action_vector(frame)
            if state is None:
                continue

            item = {
                "observation.state": state,
                # action 缺字段时退化为 state（保证形状一致，不丢帧）
                "action": action if action is not None else state[:ACTION_DIM],
                "task": self.task,
            }
            for k in img_keys:
                img = np.asarray(data[k][i])
                if img.ndim == 3:
                    item["observation.images.%s" % k] = img
            ds.add_frame(item)
            written += 1

        if written == 0:
            raise RuntimeError("episode 无有效帧（缺少 joint_pos/ee_pos 等字段）")

        ds.save_episode()
        self.saved.append(self.root)
        self._flush_episode()          # 立即落盘，避免崩溃/断电丢整集
        return "%s (ep %d, %d 帧)" % (self.root, episode.episode_id, written)

    def _flush_episode(self) -> None:
        """每集存档后立刻把数据/元数据刷到磁盘。

        为什么需要（重要）
        ------------------
        lerobot 默认 `metadata_buffer_size=10`：meta/episodes 要攒满
        10 集才写一次。若中途崩溃/断电/被杀进程，**已录的集全部读不出来**
        （表现为 meta/episodes 缺失，lerobot 转而去找 HuggingFace 报 401）。

        这里做两件可重入的事（都不调 finalize —— 它是一次性锁死的）：
          * `writer.close_writer()` -> 关 parquet writer，写 footer
          * `meta._flush_metadata_buffer()` -> 把 meta/episodes 立刻落盘
        """
        ds = self._dataset
        if ds is None:
            return
        # 只刷 meta/episodes（可重入：写完 buffer 会 clear）。
        #
        # 注意：**不要**在这里调 writer.close_writer()。
        # 因为 _pq_writer 是踩在同一个 file-000.parquet 上追加写入的，
        # 一旦中途 close，下一集会以覆盖模式重建 writer，
        # 反而把前面数据的 footer/内容写坏（实测 ArrowInvalid）。
        # parquet 的 footer 统一交给 close()/finalize() 收尾；
        # 这里只保证「已录集数的元数据」不丢，即使进程中途崩溃，
        # 至少能定位到已写入的帧。
        try:
            meta = getattr(ds, "meta", None)
            fl = getattr(meta, "_flush_metadata_buffer", None)
            if callable(fl):
                fl()
        except Exception as e:                              # noqa: BLE001
            print("[LeRobot] [warn] flush metadata 失败: %s: %s" % (type(e).__name__, e))

    @property
    def n_saved(self) -> int:
        return len(self.saved)

    # ------------------------------------------------------------ 收尾
    def close(self) -> None:
        """写 parquet footer 并释放。不调用会导致 parquet 缺 footer 无法读取。"""
        if self._dataset is None:
            return
        try:
            finalize = getattr(self._dataset, "finalize", None)
            if callable(finalize):
                finalize()
        except Exception:                                    # noqa: BLE001
            pass
        try:
            stop = getattr(self._dataset, "stop_image_writer", None)
            if callable(stop):
                stop()
        except Exception:                                    # noqa: BLE001
            pass

    def __del__(self):
        """兜底：进程退出/被回收时尽量把 footer 和 meta 写下去。

        正常流程应显式调 close()；这里只是防止忘记调用导致数据集损坏。
        """
        try:
            if getattr(self, "_dataset", None) is not None:
                self.close()
        except Exception:                                    # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
