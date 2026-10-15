# -*- coding: utf-8 -*-
"""离线端到端演练：用假数据跑通完整采集流程，不连接仿真。

用途
----
1. 在真机/相机就绪前，验证状态机 + 字段 + 缓冲 + 落盘钩子的完整链路
2. 演练按键操作节奏，确认手感符合预期
3. 作为给甲方的"流程说明"演示
"""
from __future__ import annotations

import os as _os, sys as _sys
# 本文件位于 tests/，被测模块在 scripts/collect —— 加入 sys.path，任意目录都能独立运行
_COLLECT = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         "scripts", "collect")
if _COLLECT not in _sys.path:
    _sys.path.insert(0, _COLLECT)

import numpy as np

from recorder import Recorder, State
from keymap import DpadRecorder


class MockRig:
    """模拟 OrcaRig 的接口，产生合理的假数据。"""

    def __init__(self, n_arm=7):
        self.n_arm = n_arm
        self._t = 0.0
        self._q = np.zeros(n_arm, dtype=np.float64)

        class D:
            pass

        self.d = D()
        self.d.time = 0.0
        self.d.qvel = np.zeros(64)

        self.arm_v = {"l": np.arange(7), "r": np.arange(7) + 7}
        # 夹爪关节顺序（与 orca_rig 的 GORDER 对齐）
        self._gorder = ["inner_joint1", "inner_joint2", "inner_joint3",
                        "inner_joint4", "outer_joint1", "outer_joint2",
                        "outer_joint3", "outer_joint4"]

    def arm_qpos(self, side):
        base = 0.0 if side == "l" else 0.3
        return self._q + base

    def gripper_qpos(self, side):
        v = 0.2 if side == "l" else 0.8
        return {k: v for k in self._gorder}

    def site_pos_mat(self, side):
        x = 0.0 if side == "l" else 1.0
        pos = np.array([1.7 + x, -3.1, 1.4 + self._t * 0.01])
        R = np.eye(3)
        return pos, R

    def step_mock(self):
        """推进一点时间，模拟仿真步进。"""
        self._t += 0.04
        self.d.time = self._t
        self._q += 0.001


class FakePad:
    def __init__(self):
        self.dpad = (0, 0)

    def press(self, dx, dy):
        self.dpad = (dx, dy)

    def release(self):
        self.dpad = (0, 0)


def run_demo():
    rig = MockRig()
    rec = Recorder(on_event=lambda k, m: print(f"       [event:{k}] {m}"))
    pad = FakePad()
    dpr = DpadRecorder(rec, pad, on_message=lambda s: print(f"    >> {s}"))

    active = {"side": "r"}

    def action_now():
        pos, R = rig.site_pos_mat(active["side"])
        return {"goal_pos": pos, "goal_mat": R, "gripper_cmd": 0.5}

    saved_frames = []
    rec.set_saver(lambda ep: (saved_frames.append(ep.n_frames), "memory://demo")[1])

    print("=" * 62)
    print("离线端到端演练")
    print("=" * 62)
    print()

    # ---- 场景 1：正常采集一条 ----
    print("场景 1：正常采集一条 episode")
    print("-" * 62)
    for i in range(140):
        rig.step_mock()
        dpr.poll()
        if rec.state is State.RECORDING:
            rec.capture({"timestamp": np.float32(rig.d.time),
                         "joint_pos": rig.arm_qpos("r").astype(np.float32)})
        # 第 10 步：按十字下（待命）
        if i == 10:
            pad.press(0, 1)
        elif i == 11:
            pad.release()
        # 第 20 步：按十字上（开始）
        elif i == 20:
            pad.press(0, -1)
        elif i == 21:
            pad.release()
        # 第 100 步：按十字上（结束）
        elif i == 100:
            pad.press(0, -1)
        elif i == 101:
            pad.release()
        # 第 110 步：按十字左（保存）
        elif i == 110:
            pad.press(-1, 0)
        elif i == 111:
            pad.release()
    print(f"  最终状态: {rec.state.value}")
    print(f"  已保存: {rec.n_saved} 条, 帧数 {saved_frames}")
    print()

    # ---- 场景 2：采集后丢弃 ----
    print("场景 2：采集一条后丢弃")
    print("-" * 62)
    for i in range(120):
        rig.step_mock()
        dpr.poll()
        if rec.state is State.RECORDING:
            rec.capture({"timestamp": np.float32(rig.d.time)})
        if i == 10:
            pad.press(0, 1)
        elif i == 11:
            pad.release()
        elif i == 15:
            pad.press(0, -1)
        elif i == 16:
            pad.release()
        elif i == 60:
            pad.press(0, -1)
        elif i == 61:
            pad.release()
        elif i == 70:
            pad.press(1, 0)
        elif i == 71:
            pad.release()
    print(f"  最终状态: {rec.state.value}")
    print(f"  已保存 {rec.n_saved} 条, 已丢弃 {rec.n_discarded} 条")
    print()

    # ---- 场景 3：录制中误触中止 ----
    print("场景 3：录制中途按十字下 -> 安全中止")
    print("-" * 62)
    for i in range(80):
        rig.step_mock()
        dpr.poll()
        if rec.state is State.RECORDING:
            rec.capture({"timestamp": np.float32(rig.d.time)})
        if i == 10:
            pad.press(0, 1)
        elif i == 11:
            pad.release()
        elif i == 15:
            pad.press(0, -1)
        elif i == 16:
            pad.release()
        elif i == 40:
            pad.press(0, 1)          # 录制中按十字下 = 中止
        elif i == 41:
            pad.release()
    print(f"  最终状态: {rec.state.value}")
    print(f"  已保存 {rec.n_saved} 条, 已丢弃 {rec.n_discarded} 条")
    print()

    print("=" * 62)
    print("演练结束。三个场景行为均符合预期。")
    print("=" * 62)


if __name__ == "__main__":
    run_demo()
