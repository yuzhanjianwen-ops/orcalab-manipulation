# -*- coding: utf-8 -*-
"""键盘设备 —— 与 Gamepad 完全同接口，供 teleop.py 无缝替换。

设计要点
--------
* **零依赖**：只用标准库 `ctypes` 调用 Windows 的
  `GetAsyncKeyState`，不需要 pygame 之类。
* **不受窗口焦点影响**：`GetAsyncKeyState` 读的是全局键盘状态，
  所以渲染窗口（MuJoCo/robosuite）抢走焦点时仍然能读到按键。
* **同接口**：`left` / `right` / `lt` / `rt` / `dpad` / `held` / `pressed` /
  `released` / `pressed_any` / `rumble` / `connected` 全部与 Gamepad 一致，
  因此 teleop.py 只需替换构造那一行。

速度控制
--------
手柄摇杆是模拟量，键盘是开关量。这里用 **Shift 作为慢速档**：
* 不按 Shift：满速（1.0）
* 按住 Shift：慢速（`slow_scale`，默认 0.25），用于精细对准
* 如果再按住 Ctrl：更慢（`slow_scale * ctrl_scale`）

键位（默认，可用 `bindings` 覆盖）
--------------------------------
    平移       W / S / A / D
    升降       R (上) / F (下)
    姿态       ↑ ↓ ← →     （方向键）
    滚转       E / Q
    夹爪       Z (闭合) / X (张开)
    切换手臂   C
    回工作位   V
    重新同步   T
    急停       SPACE（按住）
    视角切换   G
    十字键     I / K / J / L  （上/下/左/右，对应手柄 dpad）
    慢速       SHIFT（按住）
    更慢       CTRL（按住，可与 SHIFT 叠加）

说明：方向键做姿态、WASD 做平移，两者物理相邻，双手分区不冲突。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 全局键盘
# msvcrt 只能读【控制台】的键盘缓冲，一旦渲染窗口抢走焦点就彻底失灵。
# GetAsyncKeyState 读的是【全局】键盘状态，不受焦点影响，因此这里改用它。
_user32 = ctypes.windll.user32
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

# Windows 虚拟键码（VK）
VK = {
    "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44,
    "E": 0x45, "Q": 0x51, "R": 0x52, "F": 0x46,
    "Z": 0x5A, "X": 0x58, "C": 0x43, "V": 0x56,
    "T": 0x54, "G": 0x47,
    "I": 0x49, "K": 0x4B, "J": 0x4A, "L": 0x4C,
    "SPACE": 0x20,
    "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
}


def key_down(name: str) -> bool:
    """该键当前是否被按住（全局，与窗口焦点无关）。"""
    vk = VK.get(name)
    if vk is None:
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

# --------------------------------------------------------------------- 键码
# ------------------------------------------------------------------ 键位表
DEFAULT_BINDINGS = {
    # 平移（对应手柄左摇杆）
    "forward":  "W",
    "back":     "S",
    "left":     "A",
    "right":    "D",
    # 升降（对应 RT / LT）
    "up":       "R",
    "down":     "F",
    # 姿态（对应手柄右摇杆）
    "yaw_l":    "LEFT",
    "yaw_r":    "RIGHT",
    "pitch_u":  "UP",
    "pitch_d":  "DOWN",
    # 滚转（对应 RB / LB）
    "roll_p":   "E",
    "roll_n":   "Q",
    # 夹爪（对应 A / B）
    "gripper_close": "Z",
    "gripper_open":  "X",
    # 功能键（对应 X / Y / START / BACK）
    "toggle_arm": "C",
    "home":       "V",
    "resync":     "T",
    "estop":      "SPACE",
    # 视角切换（对应 R3）
    "view_toggle": "G",
    # 十字键（对应 dpad 四方向）
    "dpad_up":    "I",
    "dpad_down":  "K",
    "dpad_left":  "J",
    "dpad_right": "L",
}

# 功能键名 -> 手柄按键名（teleop.py 里 pad.held("A") 等要用手柄的名字）
_BUTTON_ALIASES = {
    "A": "gripper_close",
    "B": "gripper_open",
    "X": "toggle_arm",
    "Y": "home",
    "START": "resync",
    "BACK": "estop",
    "RB": "roll_p",
    "LB": "roll_n",
    "RSTICK": "view_toggle",
    "LSTICK": None,
    # 十字键也要登记，否则 held("DPAD_DOWN") / pressed("DPAD_UP")
    # 这类调用会一路返回 False（采集状态机就靠这个边沿）。
    # 注意：它们同时也会反映在 .dpad 元组里，两条路径保持一致。
    "DPAD_UP": "dpad_up",
    "DPAD_DOWN": "dpad_down",
    "DPAD_LEFT": "dpad_left",
    "DPAD_RIGHT": "dpad_right",
}


@dataclass
class KeypadState:
    """与 GamepadState 字段保持一致。"""

    connected: bool = True
    packet: int = 0
    buttons: int = 0
    lt: float = 0.0
    rt: float = 0.0
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    dpad: tuple[int, int] = (0, 0)
    slow: bool = False
    keys: set = field(default_factory=set)


class Keypad:
    """键盘版手柄。接口与 Gamepad 一致，可直接替换。"""

    def __init__(self, index: int = 0, deadzone: float = 0.12,
                 trigger_deadzone: float = 0.04,
                 slow_scale: float = 0.25, ctrl_scale: float = 0.4,
                 hold_timeout: float = 0.25,
                 bindings: dict | None = None, **_ignored):
        # 兼容 Gamepad 的构造参数；index / deadzone 在此无实际作用
        self.index = index
        self.deadzone = deadzone
        self.trigger_deadzone = trigger_deadzone
        self.slow_scale = float(slow_scale)
        self.ctrl_scale = float(ctrl_scale)
        # 改用 GetAsyncKeyState 后能直接读到真实 key-down，
        # 因此不再需要靠超时窗口推断「松手」。
        # 该参数保留仅为兼容旧调用（例如早期测试会传小值收窄窗口）。
        self.hold_timeout = float(hold_timeout)
        self.bindings = dict(DEFAULT_BINDINGS)
        if bindings:
            self.bindings.update(bindings)

        self._down: set[str] = set()      # 当前被认为按住的键
        self._prev_buttons = 0            # 上一帧的按键位（released 用）

        # ---- 上升沿边沿检测状态（方案B，详见 poll()）--------------------
        # msvcrt 不上报 key-up，「松开」靠 hold_timeout 超时推断。
        # 若直接用「比较两帧按位」检测上升沿，按住时系统按键重复速率一旦
        # 抖动（某帧恰好没收到该键），就会被误判成「松开 -> 又按下」，
        # 采集状态机可能因此重复前进一格。
        #   _held_prev : 上一帧的 _down，用于检测「新按下」
        #   _armed     : 已发现但尚未被消费的上升沿
        #   _edge      : 本帧真正要报告的上升沿（pressed() 读它）
        self._held_prev: set[str] = set()
        self._armed: set[str] = set()
        self._edge: set[str] = set()

        self._state = KeypadState()
        self._drop_ext = False            # 正在丢弃扩展键的第二个字节
        self.poll()

    # -------------------------------------------------------------- 键读取
    def _read_frame(self) -> set[str]:
        """返回本帧所有被按住的键名。

        用 GetAsyncKeyState 遍历键位表 —— 它是**全局**状态，
        因此渲染窗口抢焦点也不影响；而且能直接读出「当前是否按住」，
        不需要靠超时去猜 key-up。

        这里返回的是「当前按住的集合」，poll() 内部再做上升沿检测。
        """
        return {name for name in VK if key_down(name)}

    # -------------------------------------------------------------- 轮询
    def poll(self) -> KeypadState:
        """读一次键盘，返回规范化状态快照。

        现在用 GetAsyncKeyState：它直接给出「某键当前是否按住」，
        不再需要靠超时窗口去猜 key-up，因此手感上「松手即停」，
        既没有滑行，也不受系统按键重复速率影响。
        """
        # _read_frame 返回的就是「当前按住的键集合」（全局键盘状态）
        self._down = self._read_frame()
        seen = set(self._down)

        b = self.bindings

        def hold(name: str) -> bool:
            return b.get(name, "") in self._down

        slow = "SHIFT" in self._down or "SHIFT_L" in self._down
        if "CTRL" in self._down or "CTRL_L" in self._down:
            scale = self.slow_scale * self.ctrl_scale
        elif slow:
            scale = self.slow_scale
        else:
            scale = 1.0

        # 平移 / 姿态：开关量 -> ±scale
        lx = (scale if hold("right") else 0.0) - (scale if hold("left") else 0.0)
        ly = (scale if hold("forward") else 0.0) - (scale if hold("back") else 0.0)
        rx = (scale if hold("yaw_r") else 0.0) - (scale if hold("yaw_l") else 0.0)
        ry = (scale if hold("pitch_u") else 0.0) - (scale if hold("pitch_d") else 0.0)

        lt = 1.0 if hold("down") else 0.0
        rt = 1.0 if hold("up") else 0.0

        dpad = (
            (1 if hold("dpad_right") else 0) - (1 if hold("dpad_left") else 0),
            (1 if hold("dpad_up") else 0) - (1 if hold("dpad_down") else 0),
        )

        buttons = 0
        for pad_name, key_name in _BUTTON_ALIASES.items():
            if key_name and hold(key_name):
                buttons |= BUTTON_MASKS[pad_name]

        # ---- 上升沿边沿消费（方案B）----------------------------------------
        # 规则只有三条：
        #   1) 键从「不在 _down」变为「在 _down」 -> 新上升沿，加入 _armed
        #   2) 只有 _read_frame() 本帧真正收到的键才消费 _armed（进 _edge）
        #      这保证一次按下只报告一次；后续帧因系统重复而再收到该键时，
        #      _armed 里已经没有它了。
        #   3) 键真正离开 _down（超时确认松开）-> 清掉 _armed 残留，
        #      这样下次按下才会重新产生上升沿。
        newly = self._down - self._held_prev
        if newly:
            self._armed |= newly
        self._edge = set()                    # 每帧重置：上升沿只报一次
        for k in seen:
            if k in self._armed:
                self._edge.add(k)
                self._armed.discard(k)
        for k in list(self._armed):
            if k not in self._down:
                self._armed.discard(k)        # 真正松开 -> 清理残留

        # 关键顺序：_prev_buttons 必须是「上一帧」的按键位，
        # 所以要在覆盖 _state 之前先把旧的 buttons 取出来。
        # （之前的写法把 _prev_buttons 赋成「本帧」，导致 released() 恒为假。）
        prev = self._state.buttons
        self._state = KeypadState(
            connected=True,
            packet=self._state.packet + 1,
            buttons=buttons,
            lt=lt, rt=rt,
            lx=lx, ly=ly, rx=rx, ry=ry,
            dpad=dpad,
            slow=slow,
            keys=set(self._down),
        )
        self._prev_buttons = prev
        self._held_prev = set(self._down)
        return self._state

    # -------------------------------------------------------------- 访问器
    @property
    def connected(self) -> bool:
        return True

    @property
    def state(self) -> KeypadState:
        return self._state

    @property
    def left(self) -> tuple[float, float]:
        return self._state.lx, self._state.ly

    @property
    def right(self) -> tuple[float, float]:
        return self._state.rx, self._state.ry

    @property
    def lt(self) -> float:
        return self._state.lt

    @property
    def rt(self) -> float:
        return self._state.rt

    @property
    def dpad(self) -> tuple[int, int]:
        return self._state.dpad

    @property
    def slow(self) -> bool:
        """当前是否处于慢速档（供界面提示用）。"""
        return self._state.slow

    def held(self, name: str) -> bool:
        bit = BUTTON_MASKS.get(name)
        if bit is None:
            return False
        return bool(self._state.buttons & bit)

    def pressed(self, name: str) -> bool:
        """本帧是否发生了「按下」这个上升沿。

        方案B：不靠比较两帧的按键位，而是直接读 poll() 维护的 _edge，
        因此按住时系统按键重复速率的抖动不会误触发第二次按下。
        """
        # _edge 里存的是「物理键名」（如 "Z"），而这里入参是手柄按键名
        # （如 "A"）。所以要先经 _BUTTON_ALIASES 找到键位配置名，
        # 再用 bindings 反查它对应的物理键。
        bind_name = _BUTTON_ALIASES.get(name)
        if not bind_name:
            return False
        return self.bindings.get(bind_name, "") in self._edge

    def released(self, name: str) -> bool:
        """本帧是否发生了「松开」（靠 hold_timeout 超时推断）。"""
        bit = BUTTON_MASKS.get(name)
        if bit is None:
            return False
        return (not bool(self._state.buttons & bit)) and bool(self._prev_buttons & bit)

    def pressed_any(self) -> list[str]:
        return [n for n in BUTTON_MASKS if self.pressed(n)]

    def rumble(self, left: float, right: float) -> None:
        """键盘没有震动，空实现（保持接口一致）。"""
        return None


# 与 gamepad.BUTTONS 保持一致的位掩码（键盘内部自用）
BUTTON_MASKS = {
    "DPAD_UP": 0x0001,
    "DPAD_DOWN": 0x0002,
    "DPAD_LEFT": 0x0004,
    "DPAD_RIGHT": 0x0008,
    "START": 0x0010,
    "BACK": 0x0020,
    "LSTICK": 0x0040,
    "RSTICK": 0x0080,
    "LB": 0x0100,
    "RB": 0x0200,
    "A": 0x1000,
    "B": 0x2000,
    "X": 0x4000,
    "Y": 0x8000,
}


def list_slots() -> list[int]:
    """与 gamepad.list_slots 对齐：键盘总是可用，返回 [0]。"""
    return [0]


# ------------------------------------------------------------------ 键位帮助
KEYMAP_TEXT = """
键盘遥操作 —— 键位表
──────────────────────────────────────────────
  平移             W / S / A / D
  升降             R（升） / F（降）
  姿态             ↑ ↓ ← →      （方向键）
  滚转             E / Q
  夹爪             Z（闭合） / X（张开）
  切换手臂         C
  手臂回工作位     V
  重新同步         T
  急停（按住）     SPACE
  切换视角         G
  采集十字键       I（上） K（下） J（左） L（右）

  ★ 慢速          按住 SHIFT   → 25% 速度（精细对准）
  ★ 更慢          按住 CTRL    → 10% 速度
  ★ 组合           SHIFT+CTRL  → 先按 SHIFT 再按 CTRL
──────────────────────────────────────────────
  提示：键盘是开关量，松开慢速键立即恢复满速。
        接近物体时按住 SHIFT，手感接近手柄轻推摇杆。
"""
