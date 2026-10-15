# -*- coding: utf-8 -*-
"""recorder.py 单元测试（离线，不依赖 orca_gym）。"""
import os as _os, sys as _sys
# 本文件位于 tests/，被测模块在 scripts/collect —— 加入 sys.path，任意目录都能独立运行
_COLLECT = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         "scripts", "collect")
if _COLLECT not in _sys.path:
    _sys.path.insert(0, _COLLECT)

import numpy as np
from recorder import Recorder, State, EpisodeBuffer

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print("  PASS  " + name)
    else:
        fail += 1; print("  FAIL  " + name + ("  " + str(extra) if extra else ""))

print("=== 1. 状态转移：完整正常流程 ===")
rec = Recorder()
check("初始 IDLE", rec.state is State.IDLE)
rec.arm();               check("十字下 -> READY", rec.state is State.READY)
rec.toggle_record();     check("十字上 -> REC", rec.state is State.RECORDING)
for i in range(5):
    rec.capture({"joint_pos": np.zeros(14), "t": i})
check("录到 5 帧", rec.episode.n_frames == 5, rec.episode.n_frames)
rec.toggle_record();     check("十字上 -> REVIEW", rec.state is State.REVIEW)
msg = rec.save();        check("十字左 -> 保存", rec.n_saved == 1 and rec.state is State.IDLE, msg)

print()
print("=== 2. 丢弃流程 ===")
rec = Recorder()
rec.arm(); rec.toggle_record()
for i in range(3): rec.capture({"t": i})
rec.toggle_record()
rec.discard()
check("丢弃后 IDLE", rec.state is State.IDLE)
check("保存数仍为 0", rec.n_saved == 0)
check("丢弃计数 1", rec.n_discarded == 1)

print()
print("=== 3. 误触防护 ===")
rec = Recorder()
check("IDLE 按十字上无效", rec.toggle_record() == "" and rec.state is State.IDLE)
check("IDLE 按十字左无效", rec.save() == "")
check("IDLE 按十字右无效", rec.discard() == "")
rec.arm(); rec.arm()
check("READY 再按十字下 -> 取消", rec.state is State.IDLE)
rec.arm(); rec.toggle_record()
for i in range(2): rec.capture({"t": i})
rec.arm()
check("REC 中按十字下 -> 中止丢弃", rec.state is State.IDLE and rec.n_discarded == 1)

print()
print("=== 4. RECORDING 之外不采集 ===")
rec = Recorder()
rec.capture({"t": 1})
check("IDLE 时 capture 无效", rec.episode.n_frames == 0)
rec.arm(); rec.capture({"t": 2})
check("READY 时 capture 无效", rec.episode.n_frames == 0)

print()
print("=== 5. REVIEW 中重复保存防护 ===")
rec = Recorder()
rec.arm(); rec.toggle_record(); rec.capture({"t": 1})
rec.toggle_record()
rec.save(); rec.save()
check("第二次 save 无效", rec.n_saved == 1, rec.n_saved)

print()
print("=== 6. stacked() 堆叠 ===")
buf = EpisodeBuffer()
for i in range(4):
    buf.append({"joint_pos": np.arange(14, dtype=np.float32) + i,
                "img": np.zeros((8, 8, 3), dtype=np.uint8) + i,
                "t": float(i)})
st = buf.stacked()
check("joint_pos 形状", st["joint_pos"].shape == (4, 14), st["joint_pos"].shape)
check("image 形状 (T,H,W,C)", st["img"].shape == (4, 8, 8, 3), st["img"].shape)
check("标量 t 形状", st["t"].shape == (4,), st["t"].shape)

print()
print("=== 7. 图像注入 ===")
rec = Recorder()
frame_gen = iter([np.zeros((4, 4, 3), np.uint8) + k for k in range(10)])
rec.set_image_fn(lambda: next(frame_gen, None))
rec.arm(); rec.toggle_record()
for i in range(3): rec.capture({"t": i})
check("每帧含 image", all("image" in f for f in rec.episode.frames))
check("image 值正确", rec.episode.frames[2]["image"][0, 0, 0] == 2)

print()
print("=== 8. 落盘回调注入 ===")
saved = []
rec = Recorder()
rec.set_saver(lambda ep: saved.append(ep.n_frames) or "fake_path")
rec.arm(); rec.toggle_record()
for i in range(6): rec.capture({"t": i})
rec.toggle_record()
rec.save()
check("saver 被调用且帧数正确", saved == [6], saved)

print()
print("=== 9. 多 episode 计数 ===")
rec = Recorder()
for k in range(3):
    rec.arm(); rec.toggle_record()
    for i in range(k + 1): rec.capture({"t": i})
    rec.toggle_record(); rec.save()
check("保存 3 条", rec.n_saved == 3, rec.n_saved)
check("episode_id 递增", [e.episode_id for e in rec.saved_episodes] == [0, 1, 2],
      [e.episode_id for e in rec.saved_episodes])

print()
print("=== 10. status_line 各状态 ===")
rec = Recorder()
rec.arm()
check("READY 状态行含 READY", "READY" in rec.status_line())
rec.toggle_record()
check("REC 状态行含 REC", "[REC]" in rec.status_line())

print()
print("=" * 52)
print(f"结果: {ok} passed, {fail} failed")
