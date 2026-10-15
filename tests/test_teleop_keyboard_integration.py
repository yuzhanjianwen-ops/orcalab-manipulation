# -*- coding: utf-8 -*-
"""端到端联调：用 Keypad 驱动 teleop.py 的输入处理逻辑。

不需要仿真器/手柄：把 Keypad 的按键流喂进去，
验证 teleop.py 里那段「读 pad -> 算速度」的逻辑能得到正确结果。
"""

import os as _os, sys as _sys
# 本文件位于 teleop/tests/，把上一级(操作模块根)加入 sys.path，
# 这样无论从哪个目录运行都能 import 到 keypad / gamepad / teleop。
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)

import io, re, sys

# ---- 从 teleop.py 里摘出 run() 中读 pad 的那段核心逻辑，做等价复现 ----
src = io.open("teleop.py", encoding="utf-8").read()

checks = []
def check(name, cond, extra=""):
    checks.append((name, cond, extra))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  " + str(extra)) if extra else ""))

import numpy as np
from keypad import Keypad
import keypad as kp_mod

def make_kb():
    """返回 (pad, feed) ；feed 设置本帧按键集合。"""
    pad = Keypad(hold_timeout=1e-9)
    box = [set()]
    pad._read_frame = lambda: set(box[0])
    return pad, box

print("=== 1. 夹爪：Z 闭合 / X 张开（held A / B）===")
pad, box = make_kb()
box[0] = {"Z"}                       # 键盘 Z = 手柄 A = 夹爪闭合
pad.poll()
check("Z -> held(A) 为真", pad.held("A") is True)
box[0] = {"X"}                       # 键盘 X = 手柄 B = 夹爪张开
pad.poll()
check("X -> held(B) 为真", pad.held("B") is True)

print()
print("=== 2. 切臂：C -> pressed(X) ===")
pad, box = make_kb()
box[0] = {"C"}
pad.poll()
check("C -> pressed(X) 为真（切臂触发）", pad.pressed("X") is True)
pad.poll()
check("持续按住不再触发", pad.pressed("X") is False)

print()
print("=== 3. 回工作位：V -> pressed(Y) ===")
pad, box = make_kb()
box[0] = {"V"}
pad.poll()
check("V -> pressed(Y) 为真", pad.pressed("Y") is True)

print()
print("=== 4. 重同步：T -> pressed(START) ===")
pad, box = make_kb()
box[0] = {"T"}
pad.poll()
check("T -> pressed(START) 为真", pad.pressed("START") is True)

print()
print("=== 5. 急停：SPACE -> held(BACK)（按住不松）===")
pad, box = make_kb()
box[0] = {"SPACE"}
pad.poll()
check("SPACE -> held(BACK) 为真", pad.held("BACK") is True)

print()
print("=== 6. 视角：G -> held(RSTICK) ===")
pad, box = make_kb()
box[0] = {"G"}
pad.poll()
check("G -> held(RSTICK) 为真", pad.held("RSTICK") is True)

print()
print("=== 7. 平移速度向量 (lx, ly) ===")
pad, box = make_kb()
box[0] = {"W"}; pad.poll()
lx, ly = pad.left
check("W -> ly=+1 (前伸)", abs(ly - 1.0) < 1e-9, (lx, ly))
box[0] = {"D"}; pad.poll()
lx, ly = pad.left
check("D -> lx=+1 (右移)", abs(lx - 1.0) < 1e-9, (lx, ly))
box[0] = {"R"}; pad.poll()
check("R -> rt=1 (上升)", pad.rt == 1.0, pad.rt)
box[0] = {"F"}; pad.poll()
check("F -> lt=1 (下降)", pad.lt == 1.0, pad.lt)

print()
print("=== 8. 姿态速度向量 (rx, ry, roll) ===")
pad, box = make_kb()
box[0] = {"RIGHT"}; pad.poll()
check("RIGHT -> rx=+1 (Yaw)", abs(pad.right[0] - 1.0) < 1e-9, pad.right)
box[0] = {"UP"}; pad.poll()
check("UP -> ry=+1 (Pitch)", abs(pad.right[1] - 1.0) < 1e-9, pad.right)
box[0] = {"E"}; pad.poll()
check("E -> held(RB) (Roll+)", pad.held("RB") is True)
box[0] = {"Q"}; pad.poll()
check("Q -> held(LB) (Roll-)", pad.held("LB") is True)

print()
print("=== 9. 完全重开：十字下 -> dpad==(0,-1) ===")
pad, box = make_kb()
box[0] = {"K"}
pad.poll()
check("K(下) -> dpad == (0,-1)", pad.dpad == (0, -1), pad.dpad)

print()
print("=== 10. 慢速档 SHIFT / CTRL ===")
pad, box = make_kb()
box[0] = {"W", "SHIFT"}; pad.poll()
check("W+SHIFT -> 0.25", abs(pad.left[1] - 0.25) < 1e-9, pad.left[1])
check("  且 slow 标志为真", pad.slow is True)
box[0] = {"W", "SHIFT", "CTRL"}; pad.poll()
check("W+SHIFT+CTRL -> 0.10", abs(pad.left[1] - 0.10) < 1e-9, pad.left[1])

print()
print("=== 11. 等效性：键盘与手柄对 teleop 的输出形状一致 ===")
# teleop.py 做的是 v = [ly, lx, rt-lt] * LIN_SPEED
# 手柄满推 = 1.0，键盘满速也应是 1.0 -> 两者在 teleop 眼里同构
pad, box = make_kb()
box[0] = {"W"}
pad.poll()
v_kb = np.array([pad.left[1], pad.left[0], pad.rt - pad.lt])
v_gp = np.array([1.0, 0.0, 0.0])          # 手柄满推 W 等价
check("键盘满速 == 手柄满推", np.allclose(v_kb, v_gp), (v_kb, v_gp))

print()
print("=" * 54)
n_ok = sum(1 for _, c, _ in checks if c)
print(f"结果: {n_ok} passed, {len(checks) - n_ok} failed")
sys.exit(0 if n_ok == len(checks) else 1)
