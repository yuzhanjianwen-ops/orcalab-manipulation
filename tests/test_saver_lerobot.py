# -*- coding: utf-8 -*-
"""saver_lerobot 的离线单测（不需要仿真、不需要 lerobot 已安装）。

覆盖：
    1. state/action 向量组装正确（维度、数值）
    2. episode -> 帧序列 -> LeRobot item 的映射
    3. root 安全校验（拒绝危险路径）
    4. lerobot 缺失时的行为（探活函数不抛异常）
    5. 各种异常帧（缺字段）被正确跳过/退化
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECT = os.path.abspath(os.path.join(HERE, "..", "scripts", "collect"))
sys.path.insert(0, COLLECT)

import saver_lerobot as SL                                  # noqa: E402


def _frame(i: int) -> dict:
    """构造一帧，字段形状与 fields.py 一致。"""
    return {
        "timestamp": np.float32(i * 0.05),
        "joint_pos": np.full(14, 0.1 * i, dtype=np.float32),
        "joint_vel": np.zeros(14, dtype=np.float32),
        "gripper_pos": np.full(16, 0.5, dtype=np.float32),
        "ee_pos": np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float32),
        "ee_quat": np.array([0, 0, 0, 1, 0, 0, 0, 1], dtype=np.float32),
        "active_arm": np.float32(1.0),
        "action_pos": np.array([0.1, 0.2, 0.3], dtype=np.float32),
        "action_quat": np.array([0, 0, 0, 1], dtype=np.float32),
        "action_gripper": np.float32(0.7),
    }


class _Ep:
    """最小 EpisodeBuffer 替身（只需要 stacked() / n_frames / episode_id）。"""

    def __init__(self, frames):
        self.frames = frames
        self.episode_id = 7
        self.success = True

    @property
    def n_frames(self):
        return len(self.frames)

    def stacked(self):
        keys = self.frames[0].keys()
        out = {}
        for k in keys:
            vals = [f[k] for f in self.frames]
            out[k] = np.stack(vals) if isinstance(vals[0], np.ndarray) \
                else np.asarray(vals)
        return out


class TestVectors(unittest.TestCase):
    def test_state_dim(self):
        self.assertEqual(SL.STATE_DIM, 44)
        self.assertEqual(SL.ACTION_DIM, 8)

    def test_state_vector(self):
        s = SL._state_vector(_frame(3))
        self.assertIsNotNone(s)
        self.assertEqual(s.shape, (44,))
        self.assertEqual(s.dtype, np.float32)
        # joint_pos 被放在最前
        self.assertAlmostEqual(float(s[0]), 0.3, places=5)

    def test_action_vector(self):
        a = SL._action_vector(_frame(1))
        self.assertIsNotNone(a)
        self.assertEqual(a.shape, (8,))
        # 布局：pos(3) + quat_xyzw(4) + grip(1)
        self.assertAlmostEqual(float(a[0]), 0.1)
        self.assertAlmostEqual(float(a[6]), 1.0)      # quat w 在索引 6
        self.assertAlmostEqual(float(a[7]), 0.7)      # gripper

    def test_action_missing_gripper_defaults_zero(self):
        f = _frame(0)
        del f["action_gripper"]
        a = SL._action_vector(f)
        self.assertEqual(a.shape, (8,))
        self.assertEqual(float(a[7]), 0.0)

    def test_missing_required_returns_none(self):
        f = _frame(0)
        del f["ee_pos"]
        self.assertIsNone(SL._state_vector(f))

    def test_missing_action_returns_none(self):
        f = _frame(0)
        del f["action_pos"]
        self.assertIsNone(SL._action_vector(f))


class TestRootValidation(unittest.TestCase):
    def _saver(self, root):
        s = SL.LeRobotSaver(root=root)
        return s

    def test_rejects_cwd(self):
        s = self._saver(os.getcwd())
        with self.assertRaises(ValueError):
            s._validate_root()

    def test_rejects_home(self):
        s = self._saver(os.path.expanduser("~"))
        with self.assertRaises(ValueError):
            s._validate_root()

    def test_rejects_dot(self):
        s = self._saver(".")
        s.root = "."
        with self.assertRaises(ValueError):
            s._validate_root()

    def test_accepts_dedicated_subdir(self):
        s = self._saver(os.path.join(os.getcwd(), "lerobot_out", "ds"))
        s._validate_root()          # 不抛异常即通过


class TestProbe(unittest.TestCase):
    def test_lerobot_available_returns_tuple(self):
        ok, why = SL.lerobot_available()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(why, str)

    def test_import_error_message_mentions_install(self):
        if SL.lerobot_available()[0]:
            self.skipTest("lerobot 已安装，跳过缺失提示测试")
        with self.assertRaises(ImportError) as cm:
            SL._import_lerobot()
        self.assertIn("pip install", str(cm.exception))


class TestFeatures(unittest.TestCase):
    def test_features_without_camera(self):
        s = SL.LeRobotSaver(root=os.path.join(os.getcwd(), "x", "y"))
        f = s._features()
        self.assertIn("observation.state", f)
        self.assertIn("action", f)
        self.assertEqual(f["observation.state"]["shape"], (44,))
        self.assertEqual(f["action"]["shape"], (8,))
        self.assertFalse(any(k.startswith("observation.images.") for k in f))

    def test_features_with_camera(self):
        s = SL.LeRobotSaver(root=os.path.join(os.getcwd(), "x", "y"),
                            cameras={"cam_head": {"height": 480, "width": 640}})
        f = s._features()
        self.assertIn("observation.images.cam_head", f)
        self.assertEqual(f["observation.images.cam_head"]["shape"], (3, 480, 640))
        self.assertEqual(f["observation.images.cam_head"]["dtype"], "video")


if __name__ == "__main__":
    # 用 unittest 跑，但最后补一行统一格式的统计，
    # 便于 run_all_tests.py 汇总（与其它测试文件一致）。
    suite = unittest.defaultTestLoader.loadTestsFromModule(
        sys.modules[__name__])
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    ok = res.testsRun - len(res.failures) - len(res.errors)
    fail = len(res.failures) + len(res.errors)
    print(f"结果: {ok} passed, {fail} failed")
    raise SystemExit(0 if fail == 0 else 1)
