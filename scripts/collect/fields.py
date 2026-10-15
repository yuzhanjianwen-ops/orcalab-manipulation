# -*- coding: utf-8 -*-
"""每帧观测/动作的字段采集（依赖 orca_gym，需先导入 orca_boot）。

字段命名参考甲方 G1OmniPickerDataStorage 的 HDF5 设计，但做了裁剪与适配：
* 保留：关节位置/速度、夹爪位置、末端位姿、动作目标
* 去掉：底盘（front_drive）、body_slide（本机器人无此关节）
* 新增：active_arm 标记（本程序一次只控制一条手臂）
"""
from __future__ import annotations

from typing import Optional

import numpy as np


# ------------------------------------------------------------------ 位姿工具
def mat_to_quat(R: np.ndarray) -> np.ndarray:
    """3x3 旋转矩阵 -> 四元数 [x, y, z, w]（与甲方存储的 xyzw 顺序一致）。"""
    from scipy.spatial.transform import Rotation as Rot

    q = Rot.from_matrix(R).as_quat()          # scipy 默认即 xyzw
    return np.asarray(q, dtype=np.float32)


def mat_to_6d(R: np.ndarray) -> np.ndarray:
    """3x3 旋转矩阵 -> 6D 旋转表示（取前两列），常用于神经网络输入。"""
    return np.asarray(R[:, :2].reshape(6), dtype=np.float32)


# ------------------------------------------------------------------ 采集器
class FrameGrabber:
    """从 OrcaRig 抓取单帧数据。

    Parameters
    ----------
    rig : OrcaRig
        已连接的遥操作装备层。
    active_arm : callable
        返回当前活动臂 "l" / "r" 的函数（采数据时随 X 键变化）。
    include_rotation_6d : bool
        除四元数外是否再存一份 6D 旋转表示。
    """

    def __init__(self, rig, active_arm=None, include_rotation_6d: bool = False):
        self.rig = rig
        self._active_arm = active_arm or (lambda: "r")
        self.include_rotation_6d = include_rotation_6d
        self.t0: Optional[float] = None

    # ------------------------------------------------------------ 主入口
    def __call__(self, action: Optional[dict] = None) -> dict:
        """采集一帧。action 为本次下发的动作（末端目标位姿 + 夹爪指令）。"""
        rig = self.rig
        d = rig.d
        now = float(d.time)
        if self.t0 is None:
            self.t0 = now

        frame: dict = {"timestamp": np.float32(now - self.t0)}

        # ---- 机器人状态：双臂关节 --------------------------------
        qpos_l = rig.arm_qpos("l").astype(np.float32)
        qpos_r = rig.arm_qpos("r").astype(np.float32)
        frame["joint_pos"] = np.concatenate([qpos_l, qpos_r])

        qvel_l = np.asarray(d.qvel[rig.arm_v["l"]], dtype=np.float32)
        qvel_r = np.asarray(d.qvel[rig.arm_v["r"]], dtype=np.float32)
        frame["joint_vel"] = np.concatenate([qvel_l, qvel_r])

        # ---- 机器人状态：夹爪 ------------------------------------
        gl = rig.gripper_qpos("l")
        gr = rig.gripper_qpos("r")
        frame["gripper_pos"] = np.array(
            [gl[k] for k in sorted(gl)] + [gr[k] for k in sorted(gr)],
            dtype=np.float32,
        )

        # ---- 机器人状态：末端位姿（双臂）--------------------------
        ee_p, ee_q = [], []
        for side in ("l", "r"):
            pos, R = rig.site_pos_mat(side)
            ee_p.append(np.asarray(pos, dtype=np.float32))
            ee_q.append(mat_to_quat(R))
        frame["ee_pos"] = np.concatenate(ee_p)          # 6 维
        frame["ee_quat"] = np.concatenate(ee_q)         # 8 维

        # ---- 动作（遥操作下发的目标）-----------------------------
        side = self._active_arm()
        frame["active_arm"] = np.float32(0.0 if side == "l" else 1.0)
        if action is not None:
            if action.get("goal_pos") is not None:
                frame["action_pos"] = np.asarray(action["goal_pos"],
                                                 dtype=np.float32)
            if action.get("goal_mat") is not None:
                R = np.asarray(action["goal_mat"], dtype=np.float64)
                frame["action_quat"] = mat_to_quat(R)
                if self.include_rotation_6d:
                    frame["action_rot6d"] = mat_to_6d(R)
            if action.get("gripper_cmd") is not None:
                frame["action_gripper"] = np.float32(action["gripper_cmd"])

        return frame

    # ------------------------------------------------------------ 字段说明
    @staticmethod
    def schema() -> dict[str, tuple]:
        """字段 -> 形状/含义，用于文档与校验。"""
        return {
            "timestamp":       ((),      "相对录制开始的秒数"),
            "joint_pos":       ((14,),   "双臂 7+7 关节角"),
            "joint_vel":       ((14,),   "双臂 7+7 关节角速度"),
            "gripper_pos":     ((16,),   "双夹爪 8+8 关节角"),
            "ee_pos":          ((6,),    "双臂末端位置 xyz"),
            "ee_quat":         ((8,),    "双臂末端姿态四元数 xyzw"),
            "active_arm":      ((),      "0=左臂 1=右臂"),
            "action_pos":      ((3,),    "活动臂末端目标位置"),
            "action_quat":     ((4,),    "活动臂末端目标姿态 xyzw"),
            "action_rot6d":    ((6,),    "目标姿态 6D 表示（可选）"),
            "action_gripper":  ((),      "夹爪开合指令"),
            "image":           ("(H,W,3)", "相机图像 uint8（相机就绪后才有）"),
        }
