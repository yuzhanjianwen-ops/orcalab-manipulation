# -*- coding: utf-8 -*-
"""Zero-dependency Xbox/XInput gamepad reader for the OrcaLab teleop stack.

Why XInput instead of pygame:
  * ctypes is built into CPython, so the teleop program needs no extra package.
  * Triggers come back as two independent 0..255 values instead of one shared
    axis, which is exactly what we want for a gripper command.
  * Button layout is fixed by Microsoft, so there is no per-pad remapping.

The Flydigi Vader 5 Pro used here enumerates as an "Xbox 360 Controller for
Windows" (XnaComposite) and is visible in XInput slot 0.

Usage:
    pad = Gamepad()
    pad.poll()                       # once per control tick
    pad.left[0], pad.left[1]         # left stick  x,y  in [-1, 1]
    pad.right[0], pad.right[1]       # right stick x,y  in [-1, 1]
    pad.lt, pad.rt                   # triggers in [0, 1]
    pad.dpad                         # (x, y) each in {-1, 0, 1}
    pad.pressed("A")                 # rising edge this tick
    pad.held("RB")                   # level this tick
    pad.rumble(0.3, 0.3)
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

# ---------------------------------------------------------------- structures
class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", _XINPUT_GAMEPAD),
    ]


class _XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]


# Button bit flags (Microsoft layout)
BUTTONS = {
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

ERROR_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167


@dataclass
class GamepadState:
    connected: bool = False
    packet: int = 0
    buttons: int = 0
    lt: float = 0.0
    rt: float = 0.0
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    dpad: tuple[int, int] = (0, 0)


class Gamepad:
    """Poll an XInput gamepad; raises if no slot is connected at construction."""

    def __init__(self, index: int = 0, deadzone: float = 0.12,
                 trigger_deadzone: float = 0.04, dll: str = "xinput1_4.dll"):
        self.index = int(index)
        self.deadzone = float(deadzone)
        self.trigger_deadzone = float(trigger_deadzone)
        self._dll = ctypes.windll.LoadLibrary(dll)
        self._dll.XInputGetState.argtypes = [
            wintypes.DWORD, ctypes.POINTER(_XINPUT_STATE)
        ]
        self._dll.XInputGetState.restype = wintypes.DWORD
        self._dll.XInputSetState.argtypes = [
            wintypes.DWORD, ctypes.POINTER(_XINPUT_VIBRATION)
        ]
        self._dll.XInputSetState.restype = wintypes.DWORD

        self._prev_buttons = 0
        self._state = GamepadState()
        if not self.connected:
            raise RuntimeError(
                f"no XInput gamepad in slot {self.index} "
                "(move the stick to wake it, then retry)"
            )
        self.poll()

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _dz(value: float, dead: float) -> float:
        """Radial-ish per-axis deadzone with a smooth rescale to [-1, 1]."""
        if abs(value) < dead:
            return 0.0
        sign = 1.0 if value > 0 else -1.0
        return sign * (abs(value) - dead) / (1.0 - dead)

    # -------------------------------------------------------------- polling
    @property
    def connected(self) -> bool:
        st = _XINPUT_STATE()
        return self._dll.XInputGetState(self.index, ctypes.byref(st)) == ERROR_SUCCESS

    def poll(self) -> GamepadState:
        """Read the pad once.  Returns the normalised state snapshot."""
        st = _XINPUT_STATE()
        rc = self._dll.XInputGetState(self.index, ctypes.byref(st))
        if rc != ERROR_SUCCESS:
            self._state = GamepadState(connected=False)
            return self._state
        g = st.Gamepad
        self._prev_buttons = self._state.buttons

        raw_lx = g.sThumbLX / 32767.0
        raw_ly = g.sThumbLY / 32767.0
        raw_rx = g.sThumbRX / 32767.0
        raw_ry = g.sThumbRY / 32767.0
        # Radial deadzone on each stick so diagonal drift does not leak.
        lx, ly = self._stick(raw_lx, raw_ly)
        rx, ry = self._stick(raw_rx, raw_ry)

        def trig(raw: int) -> float:
            v = raw / 255.0
            return 0.0 if v < self.trigger_deadzone else v

        dpad = (
            int(bool(g.wButtons & BUTTONS["DPAD_RIGHT"]))
            - int(bool(g.wButtons & BUTTONS["DPAD_LEFT"])),
            int(bool(g.wButtons & BUTTONS["DPAD_UP"]))
            - int(bool(g.wButtons & BUTTONS["DPAD_DOWN"])),
        )
        self._state = GamepadState(
            connected=True,
            packet=int(st.dwPacketNumber),
            buttons=int(g.wButtons),
            lt=trig(g.bLeftTrigger),
            rt=trig(g.bRightTrigger),
            lx=lx, ly=ly, rx=rx, ry=ry,
            dpad=dpad,
        )
        return self._state

    def _stick(self, x: float, y: float) -> tuple[float, float]:
        mag = (x * x + y * y) ** 0.5
        if mag < self.deadzone:
            return 0.0, 0.0
        scale = (mag - self.deadzone) / (1.0 - self.deadzone) / mag
        return x * scale, y * scale

    # ------------------------------------------------------------- accessors
    @property
    def state(self) -> GamepadState:
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

    def held(self, name: str) -> bool:
        return bool(self._state.buttons & BUTTONS[name])

    def pressed(self, name: str) -> bool:
        """Rising edge: was up last tick, is down now."""
        bit = BUTTONS[name]
        return bool(self._state.buttons & bit) and not bool(self._prev_buttons & bit)

    def released(self, name: str) -> bool:
        bit = BUTTONS[name]
        return (not bool(self._state.buttons & bit)) and bool(self._prev_buttons & bit)

    def pressed_any(self) -> list[str]:
        return [n for n in BUTTONS if self.pressed(n)]

    # ---------------------------------------------------------------- rumble
    def rumble(self, left: float, right: float) -> None:
        vib = _XINPUT_VIBRATION(
            int(max(0.0, min(1.0, left)) * 65535),
            int(max(0.0, min(1.0, right)) * 65535),
        )
        self._dll.XInputSetState(self.index, ctypes.byref(vib))


def list_slots() -> list[int]:
    """Return the XInput slot indices that currently have a pad."""
    dll = ctypes.windll.LoadLibrary("xinput1_4.dll")
    out = []
    for i in range(4):
        st = _XINPUT_STATE()
        if dll.XInputGetState(i, ctypes.byref(st)) == ERROR_SUCCESS:
            out.append(i)
    return out
