# -*- coding: utf-8 -*-
"""真机语义自检（GetAsyncKeyState 版）。

改用 GetAsyncKeyState 后：_read_frame 返回「当前按住的真实集合」，
能直接读到 key-down，因此不再需要超时猜「松手」。

仍然成立的两个核心保证：
  1. 一次按住 = 恰好一次 pressed()（不受按键重复速率影响）
  2. 松手立即生效，没有滑行
"""

import os as _os, sys as _sys
# 本文件位于 tests/，被测模块在 scripts/teleop —— 加入 sys.path 并切到该目录，
# 这样无论从哪个目录运行都能 import 到 keypad / gamepad / teleop。
_TELEOP = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                        "scripts", "teleop")
if _TELEOP not in _sys.path:
    _sys.path.insert(0, _TELEOP)
_os.chdir(_TELEOP)

import keypad

print("=== 1. 核心保证：稳定按住只报告一次 pressed ===")
p = keypad.Keypad()
frames = [{"K"}] * 10               # 真机按住时每帧都是 {'K'}
i = [0]
p._read_frame = lambda: frames[i[0]] if i[0] < len(frames) else set()
hits = 0
for n in range(10):
    i[0] = n
    p.poll()
    if p.pressed("DPAD_DOWN"):
        hits += 1
print(f"  稳定按住 10 帧 -> 报告 {hits} 次按下  (期望 1 次)")
assert hits == 1, hits

print()
print("=== 2. 松手立即生效（无滑行）===")
p2 = keypad.Keypad()
seq = [{"K"}, {"K"}, set()]
j = [0]
p2._read_frame = lambda: seq[j[0]] if j[0] < len(seq) else set()
j[0] = 0; p2.poll(); down1 = set(p2._down)
j[0] = 1; p2.poll(); down2 = set(p2._down)
j[0] = 2; p2.poll(); down3 = set(p2._down)
print(f"  按住={down1}  仍按住={down2}  松手={down3}")
assert down1 == {"K"} and down2 == {"K"} and down3 == set(), (down1, down2, down3)
print("  松手的那一帧立即清空（旧版会残留 0.25s -> 滑行）")

print()
print("=== 3. 松开后可以再次触发 ===")
p3 = keypad.Keypad()
seq3 = [{"K"}, set(), {"K"}]
k = [0]
p3._read_frame = lambda: seq3[k[0]] if k[0] < len(seq3) else set()
k[0] = 0; p3.poll(); a = p3.pressed("DPAD_DOWN")
k[0] = 1; p3.poll(); b = p3.pressed("DPAD_DOWN")
k[0] = 2; p3.poll(); c = p3.pressed("DPAD_DOWN")
print(f"  按下={a}  松手={b}  再按下={c}   (期望 True/False/True)")
assert (a, b, c) == (True, False, True), (a, b, c)

print()
print("=== 4. 十字四方向 held 均可读（含 DPAD_* 别名）===")
for key, name in [("I", "DPAD_UP"), ("K", "DPAD_DOWN"),
                  ("J", "DPAD_LEFT"), ("L", "DPAD_RIGHT")]:
    p4 = keypad.Keypad()
    p4._read_frame = (lambda kk: (lambda: {kk}))(key)
    p4.poll()
    print(f"  {key} -> held({name})={p4.held(name)}  pressed({name})={p4.pressed(name)}")
    assert p4.held(name) and p4.pressed(name)

print()
print("=== 5. 慢速档 ===")
p5 = keypad.Keypad()
p5._read_frame = lambda: {"W", "SHIFT"}
p5.poll()
assert abs(p5.left[1] - 0.25) < 1e-9, p5.left[1]
p5._read_frame = lambda: {"W", "SHIFT", "CTRL"}
p5.poll()
assert abs(p5.left[1] - 0.10) < 1e-9, p5.left[1]
print("  SHIFT=25%, SHIFT+CTRL=10%  正确")

print()
print("全部通过 —— GetAsyncKeyState 版语义正确。")
