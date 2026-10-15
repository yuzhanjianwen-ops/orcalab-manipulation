# -*- coding: utf-8 -*-
"""keypad.py 测试：用注入的假按键流模拟真实按键，不依赖真人操作。

关键：把 Keypad._read_events 设为可注入函数，从而喂入受控的按键序列。
"""

import os as _os, sys as _sys
# 本文件位于 teleop/tests/，把上一级(操作模块根)加入 sys.path，
# 这样无论从哪个目录运行都能 import 到 keypad / gamepad / teleop。
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_os.chdir(_ROOT)

import time
import keypad
from keypad import Keypad, BUTTON_MASKS

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  PASS  " + name)
    else:    fail += 1; print("  FAIL  " + name + ("  " + str(extra) if extra else ""))


class FakeKB:
    """假的键盘缓冲：喂入按键序列。"""
    def __init__(self): self.buf = []
    def feed(self, *keys):
        """keys 形如 'W' / 'LEFT' / 'SHIFT'"""
        self.buf.extend(keys)


def make_pad():
    kb = FakeKB()
    # hold_timeout 设成极小值：测试里每一帧都应是「独立一帧」，
    # 即上一帧按下的键在本帧就视为已松开。真实使用仍是 0.25s，
    # 那是为了对抗 msvcrt 不上报 key-up 而刻意留的宽容窗口。
    p = Keypad(hold_timeout=1e-9)
    # 替换内部读取：把 FakeKB 的内容当成「本帧收到的键」
    def reader():
        seen, kb.buf = set(kb.buf), []
        return seen
    p._read_frame = reader
    return p, kb


print("=== 1. 构造与接口完整性 ===")
p, kb = make_pad()
for attr in ["poll","left","right","lt","rt","dpad","held","pressed",
             "released","pressed_any","rumble","connected","state","slow"]:
    check(f"有 {attr}", hasattr(p, attr))
check("connected 为 True", p.connected is True)

print()
print("=== 2. 平移：WASD ===")
p, kb = make_pad()
kb.feed("W"); p.poll()
check("W -> ly 满速正", abs(p.left[1] - 1.0) < 1e-6, p.left)
kb.feed("S"); p.poll()
check("S -> ly 满速负", abs(p.left[1] + 1.0) < 1e-6, p.left)
kb.feed("D"); p.poll()
check("D -> lx 满速正", abs(p.left[0] - 1.0) < 1e-6, p.left)
kb.feed("A"); p.poll()
check("A -> lx 满速负", abs(p.left[0] + 1.0) < 1e-6, p.left)

print()
print("=== 3. Shift 慢速 ===")
p, kb = make_pad()
kb.feed("W", "SHIFT"); p.poll()
check("W+SHIFT -> 0.25", abs(p.left[1] - 0.25) < 1e-6, p.left[1])
check("slow 标志为真", p.slow is True)
kb.feed("W"); p.poll()
check("松开 SHIFT 回满速", abs(p.left[1] - 1.0) < 1e-6, p.left[1])
check("slow 标志为假", p.slow is False)

print()
print("=== 4. Ctrl 更慢 + 叠加 ===")
p, kb = make_pad()
kb.feed("W", "CTRL"); p.poll()
check("W+CTRL -> 0.10", abs(p.left[1] - 0.10) < 1e-6, p.left[1])
kb.feed("W", "SHIFT", "CTRL"); p.poll()
check("W+SHIFT+CTRL -> 0.10", abs(p.left[1] - 0.10) < 1e-6, p.left[1])

print()
print("=== 5. 姿态：方向键 ===")
p, kb = make_pad()
kb.feed("LEFT"); p.poll()
check("LEFT -> rx 负", abs(p.right[0] + 1.0) < 1e-6, p.right)
kb.feed("RIGHT"); p.poll()
check("RIGHT -> rx 正", abs(p.right[0] - 1.0) < 1e-6, p.right)
kb.feed("UP"); p.poll()
check("UP -> ry 正", abs(p.right[1] - 1.0) < 1e-6, p.right)
kb.feed("DOWN"); p.poll()
check("DOWN -> ry 负", abs(p.right[1] + 1.0) < 1e-6, p.right)

print()
print("=== 6. 升降：R / F ===")
p, kb = make_pad()
kb.feed("R"); p.poll()
check("R -> rt=1", p.rt == 1.0, p.rt)
kb.feed("F"); p.poll()
check("F -> lt=1", p.lt == 1.0, p.lt)

print()
print("=== 7. 夹爪 A/B 别名映射 ===")
p, kb = make_pad()
kb.feed("Z"); p.poll()
check("Z(闭合) -> held(A) 为真", p.held("A") is True)
check("Z 同时 pressed(A)", p.pressed("A") is True)
kb.feed("X"); p.poll()
check("X(张开) -> held(B) 为真", p.held("B") is True)

print()
print("=== 8. 功能键别名 ===")
p, kb = make_pad()
for key, pad_name in [("C","X"), ("V","Y"), ("T","START"),
                      ("SPACE","BACK"), ("G","RSTICK")]:
    kb.feed(key); p.poll()
    check(f"{key} -> {pad_name}", p.held(pad_name) is True, pad_name)

print()
print("=== 9. 上升沿 pressed / released ===")
p, kb = make_pad()
kb.feed("C"); p.poll()
check("首次按下 pressed 为真", p.pressed("X") is True)
kb.feed("C"); p.poll()
check("持续按住 pressed 为假", p.pressed("X") is False)
check("持续按住 held 为真", p.held("X") is True)
p.poll()                       # 超时后抬起
check("松开后 held 为假", p.held("X") is False)
check("松开瞬间 released 为真", p.released("X") is True)

print()
print("=== 10. 十字键（采集用）===")
p, kb = make_pad()
kb.feed("I"); p.poll()
check("I -> dpad 上 = (0,1)", p.dpad == (0, 1), p.dpad)
kb.feed("K"); p.poll()
check("K -> dpad 下 = (0,-1)", p.dpad == (0, -1), p.dpad)
kb.feed("J"); p.poll()
check("J -> dpad 左 = (-1,0)", p.dpad == (-1, 0), p.dpad)
kb.feed("L"); p.poll()
check("L -> dpad 右 = (1,0)", p.dpad == (1, 0), p.dpad)

print()
print("=== 11. 滚转 RB/LB ===")
p, kb = make_pad()
kb.feed("E"); p.poll()
check("E -> held(RB)", p.held("RB") is True)
kb.feed("Q"); p.poll()
check("Q -> held(LB)", p.held("LB") is True)

print()
print("=== 12. 未知键不出错 ===")
p, kb = make_pad()
kb.feed("Z", "BOGUS", "1", "9"); p.poll()
check("混合未知键不崩", p.held("A") is True)
kb.feed(); p.poll()
check("无输入时摇杆归零", p.left == (0.0, 0.0), p.left)

print()
print("=== 13. 位掩码与 gamepad 一致 ===")
try:
    from gamepad import BUTTONS
    same = all(BUTTON_MASKS.get(k) == v for k, v in BUTTONS.items())
    check("BUTTON_MASKS 与 gamepad.BUTTONS 完全一致", same)
except Exception as e:
    check("导入 gamepad 对比", False, e)

print()
print("=== 14. list_slots 兼容 ===")
check("list_slots() 返回 [0]", keypad.list_slots() == [0])

print()
print("=" * 54)
print(f"结果: {ok} passed, {fail} failed")
