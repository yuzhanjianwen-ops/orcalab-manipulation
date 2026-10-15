# -*- coding: utf-8 -*-
"""十字键 -> 采集状态机 的映射层（含边沿检测与防抖）。

按键盘布局（与 teleop.py 一致）：

    十字下  arm()        进入待命 / 取消 / 中止录制
    十字上  toggle_record()  开始 / 结束录制
    十字左  save()       保存当前 episode
    十字右  discard()    丢弃当前 episode

手柄 dpad 是"电平"信号（按住为 1），所以这里做**上升沿检测**：
一次按下只触发一次动作，长按不会连发。
"""
from __future__ import annotations

from typing import Callable, Optional

from recorder import Recorder


# 十字键 -> Recorder 方法名
DEFAULT_BINDINGS = {
    "down":  "arm",
    "up":    "toggle_record",
    "left":  "save",
    "right": "discard",
}


class DpadRecorder:
    """把 Gamepad 的 dpad 状态接到 Recorder 上。"""

    def __init__(self, recorder: Recorder, gamepad,
                 bindings: Optional[dict] = None,
                 on_message: Optional[Callable[[str], None]] = None):
        self.rec = recorder
        self.pad = gamepad
        self.bindings = dict(bindings or DEFAULT_BINDINGS)
        self._prev = {"up": 0, "down": 0, "left": 0, "right": 0}
        self._on_message = on_message or (lambda s: None)

    # ---------------------------------------------------------------- 轮询
    def poll(self) -> list[str]:
        """每控制周期调用一次；返回本次触发的提示信息列表。"""
        msgs: list[str] = []
        cur = self._read_dpad()
        for key, val in cur.items():
            rising = (val != 0) and (self._prev.get(key, 0) == 0)
            if rising:
                method_name = self.bindings.get(key)
                if method_name:
                    fn = getattr(self.rec, method_name, None)
                    if fn is not None:
                        msg = fn()
                        if msg:
                            msgs.append(msg)
                            self._on_message(msg)
        self._prev = cur
        return msgs

    def _read_dpad(self) -> dict:
        """读取手柄 dpad，兼容多种 attribute 形态。"""
        pad = self.pad
        try:
            dx, dy = pad.dpad
            # 权威约定来自 gamepad.py：
            #     dpad = ( RIGHT - LEFT ,  UP - DOWN )
            # 也就是说 dy = +1 表示按下了「上」，dy = -1 表示按下了「下」。
            # （此前这里写反了，导致按「上」触发 arm、按「下」触发录制，
            #   与设计要求正好相反。）
            return {
                "left":  int(dx < 0),
                "right": int(dx > 0),
                "up":    int(dy > 0),
                "down":  int(dy < 0),
            }
        except Exception:                                        # noqa: BLE001
            return {"left": 0, "right": 0, "down": 0, "up": 0}


class KeyboardFallback:
    """无手柄时的键盘替代（方便无硬件调试）。

    上=W  下=S  左=A  右=D   （单次按下触发一次，不需要回车）
    """

    def __init__(self, recorder: Recorder):
        self.rec = recorder
        self._prev: dict[str, int] = {}

    def poll(self) -> list[str]:
        import msvcrt

        msgs: list[str] = []
        while msvcrt.kbhit():
            ch = msvcrt.getch().lower()
            action = {b"w": "up", b"s": "down", b"a": "left",
                      b"d": "right"}.get(ch)
            if action is None:
                continue
            fn = getattr(self.rec, DEFAULT_BINDINGS[action], None)
            if fn:
                msg = fn()
                if msg:
                    msgs.append(msg)
        return msgs
