# -*- coding: utf-8 -*-
"""keymap.py 单元测试：边沿检测、映射、长按不连发。"""
import numpy as np
from recorder import Recorder, State
from keymap import DpadRecorder

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  PASS  " + name)
    else:    fail += 1; print("  FAIL  " + name + ("  " + str(extra) if extra else ""))

class FakePad:
    """可控的假手柄。"""
    def __init__(self): self.dpad = (0, 0)
    def press(self, dx, dy): self.dpad = (dx, dy)
    def release(self): self.dpad = (0, 0)

print("=== 1. 十字下 -> 待命 ===")
pad = FakePad(); rec = Recorder(); dpr = DpadRecorder(rec, pad)
pad.press(0, -1)                      # 按下「下」（dy=-1 为下，见 gamepad.py）
dpr.poll()
check("十字下进入 READY", rec.state is State.READY, rec.state)

print()
print("=== 2. 长按不连发 ===")
msgs = []
for _ in range(10):
    msgs += dpr.poll()                # 保持按住
check("长按只触发 1 次", len(msgs) == 0, msgs)  # 已在 READY，再按无输出
check("状态未被重复切换", rec.state is State.READY, rec.state)

print()
print("=== 3. 松开再按才再次触发 ===")
pad.release(); dpr.poll()
pad.press(0, -1); msgs = dpr.poll()
check("松开后重按 -> 取消待命", rec.state is State.IDLE and len(msgs) == 1, (rec.state, msgs))
pad.release(); dpr.poll()

print()
print("=== 4. 完整采集流程（十字上/左）===")
pad.press(0, -1); dpr.poll(); pad.release(); dpr.poll()  # 待命
check("READY", rec.state is State.READY, rec.state)
pad.press(0, 1); dpr.poll(); pad.release(); dpr.poll()   # 十字上 = 开始
check("十字上 -> REC", rec.state is State.RECORDING, rec.state)
for i in range(4): rec.capture({"t": i})
pad.press(0, 1); dpr.poll(); pad.release(); dpr.poll()   # 十字上 = 结束
check("十字上再按 -> REVIEW", rec.state is State.REVIEW, rec.state)
pad.press(-1, 0); dpr.poll(); pad.release(); dpr.poll()  # 十字左 = 保存
check("十字左 -> 保存并回 IDLE", rec.n_saved == 1 and rec.state is State.IDLE,
      (rec.n_saved, rec.state))

print()
print("=== 5. 十字右 = 丢弃 ===")
rec2 = Recorder(); dpr2 = DpadRecorder(rec2, pad)
pad.press(0, -1); dpr2.poll(); pad.release(); dpr2.poll()   # 十字下 = 待命
pad.press(0, 1); dpr2.poll(); pad.release(); dpr2.poll()    # 十字上 = 开始
for i in range(3): rec2.capture({"t": i})
pad.press(0, 1); dpr2.poll(); pad.release(); dpr2.poll()    # 十字上 = 结束
pad.press(1, 0); dpr2.poll(); pad.release(); dpr2.poll()  # 十字右
check("十字右 -> 丢弃", rec2.n_saved == 0 and rec2.n_discarded == 1,
      (rec2.n_saved, rec2.n_discarded))

print()
print("=== 6. 四个方向互不串扰 ===")
pad3 = FakePad(); rec3 = Recorder(); dpr3 = DpadRecorder(rec3, pad3)
res = {}
for name, (dx, dy) in [("left", (-1,0)), ("right", (1,0)),
                       ("up", (0,-1)), ("down", (0,1))]:
    pad3.release(); dpr3.poll()
    pad3.press(dx, dy); m = dpr3.poll()
    res[name] = len(m)
check("每次只有 1 个方向触发", all(v <= 1 for v in res.values()), res)

print()
print("=== 7. 自定义绑定 ===")
pad4 = FakePad(); rec4 = Recorder(); dpr4 = DpadRecorder(rec4, pad4,
    bindings={"down": "arm", "up": "toggle_record", "left": "save", "right": "discard"})
check("绑定表正确", dpr4.bindings["up"] == "toggle_record")

print()
print("=" * 52)
print(f"结果: {ok} passed, {fail} failed")
