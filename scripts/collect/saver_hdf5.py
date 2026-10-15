# -*- coding: utf-8 -*-
"""HDF5 落盘（备份格式）。

说明
----
甲方 OrcaManipulation 用的就是 HDF5（不是 LeRobot），字段为
`/action/joint/position`、`/action/end/position` 等。
本模块提供**同风格的 HDF5 输出**，作用有二：

1. 作为 LeRobot 就绪前的**可用备份**——先能存下数据，不阻塞采集
2. LeRobot 确定后，可作为**中间格式**（HDF5 -> LeRobot 转换脚本更好写）

目录结构（对齐甲方"每条 episode 一个 uuid 目录"的做法）::

    <dataset_path>/
        <uuid>/
            episode.hdf5
            meta.json
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional

import numpy as np

try:
    import h5py
    _HAS_H5PY = True
except ImportError:                                              # pragma: no cover
    _HAS_H5PY = False


class Hdf5Saver:
    """把 EpisodeBuffer 存成 HDF5。"""

    def __init__(self, dataset_path: str, task_name: str = "teleop",
                 use_uuid_dir: bool = True, stamp_dirs: bool = True):
        self.dataset_path = dataset_path
        self.task_name = task_name
        self.use_uuid_dir = use_uuid_dir
        # 目录名前面加采集时间戳，方便按时间排序、肉眼查找
        self.stamp_dirs = stamp_dirs
        os.makedirs(dataset_path, exist_ok=True)
        self.saved: list[str] = []

    # ---------------------------------------------------------------- 主入口
    def __call__(self, episode) -> str:
        if not _HAS_H5PY:
            raise RuntimeError("需要 h5py：请先安装 h5py")
        # 目录名：2026-09-28_164713_<短uuid>  —— 时间在前，按名字排序即按时间排序
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        if self.use_uuid_dir:
            short = str(uuid.uuid4())[:8]
            name = f"{stamp}_{short}" if self.stamp_dirs else str(uuid.uuid4())
        else:
            name = (f"{stamp}_ep{episode.episode_id:05d}" if self.stamp_dirs
                    else f"episode_{episode.episode_id:05d}")
        outdir = os.path.join(self.dataset_path, name)
        os.makedirs(outdir, exist_ok=True)
        h5path = os.path.join(outdir, "episode.hdf5")

        data = episode.stacked()
        with h5py.File(h5path, "w") as f:
            g_obs = f.create_group("observations")
            g_act = f.create_group("actions")

            for key, arr in data.items():
                if key == "image" or key.startswith("image_"):
                    g_obs.create_dataset(key, data=arr,
                                         compression="gzip", compression_opts=4)
                elif key.startswith("action_"):
                    g_act.create_dataset(key[len("action_"):], data=arr)
                elif key in ("timestamp", "active_arm"):
                    f.create_dataset(key, data=arr)
                else:
                    g_obs.create_dataset(key, data=arr,
                                         compression="gzip", compression_opts=4)

            f.attrs["task_name"] = self.task_name
            f.attrs["episode_id"] = episode.episode_id
            f.attrs["n_frames"] = episode.n_frames
            f.attrs["success"] = bool(episode.success)
            f.attrs["duration"] = float(episode.duration)
            f.attrs["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            f.attrs["source"] = "OrcaLab dual-arm teleop"

        with open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8") as fp:
            json.dump({
                "episode_id": episode.episode_id,
                "episode_dir": os.path.basename(outdir),
                "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "n_frames": episode.n_frames,
                "success": episode.success,
                "duration": episode.duration,
                "task_name": self.task_name,
                "fields": {k: list(np.shape(v)) for k, v in data.items()},
            }, fp, ensure_ascii=False, indent=2)

        self.saved.append(h5path)
        return h5path

    # ---------------------------------------------------------------- 查询
    @property
    def n_saved(self) -> int:
        return len(self.saved)
