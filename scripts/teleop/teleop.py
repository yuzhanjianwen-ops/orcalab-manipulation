# -*- coding: utf-8 -*-
"""Gamepad teleoperation of the OrcaLab dual-arm robot (velocity mode).

Control scheme (chosen with the operator):
  * end-effector VELOCITY control, expressed in the robot's base frame
  * gripper on A (close) / B (open)
  * floating base locked; arms only
  * one active arm at a time; X toggles, or pick automatically by object side
  * "left object -> left arm, right object -> right arm"

Sticks:
  left stick  X -> strafe  (base +Y, robot's left)
  left stick  Y -> forward (base +X, toward the table)
  RT / LT     -> up / down (base +Z)
  right stick X -> yaw,  right stick Y -> pitch
  LB / RB       -> roll -/+

Buttons:
  A  close gripper        B  open gripper
  X  toggle active arm    Y  return active arm to NEUTRAL
  START  re-sync goal to current pose (after a bump)
  BACK   hold = freeze (dead-man / e-stop)
  D-pad v (down)  FULL RESTART: objects + both arms + grippers back to start

Viewpoint presets (optional; the default is the stock robot-base scheme)
    python teleop.py                     # stock: sticks follow the robot
    python teleop.py --behind            # you watch from the far side
    python teleop.py --flip-lr           # only left/right feels wrong
    python teleop.py --flip-fb           # only forward/back feels wrong
    python teleop.py --view flip-lr      # same, by preset name
  While running:  R-stick click toggles the preset on/off.
  Verified operator setup (2026-09-23): --flip-lr with the camera behind the
  robot gives correct left/right, forward/back, yaw, pitch and roll.

Wrist rotation (fixed 2026-09-23)
  The wrist now rotates about the TOOL's own axes (right-multiply), not the
  world axes (left-multiply).  Before the fix, yaw was mirrored and the
  rotation axes drifted with the hand orientation, so "push right" turned the
  wrist left and pitch felt off.  Yaw also mirrors with the view now, exactly
  like the left/right translation axis.

Run:
    python teleop.py                # live, renders to OrcaLab
    python teleop.py --no-render    # headless timing check
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from orca_rig import OrcaRig, NEUTRAL          # noqa: E402
from osc_arm import OscArm, TCP_LOCAL          # noqa: E402
from gamepad import Gamepad                    # noqa: E402
# 键盘驱动是手柄之外的并行方案：默认不导入，只有在 --keyboard 时才加载。
# 这样做的好处：手柄路径的依赖、导入顺序、异常路径全部保持原样。
# （keypad.py 与 gamepad.py 接口完全一致，可无缝替换）
from teleop_view import ViewFlip, parse_flags, select_arm  # noqa: E402

# ---------------------------------------------------------------- tuning
LIN_SPEED = 0.30      # m/s at full stick
ANG_SPEED = 1.20      # rad/s at full stick
GRIP_RATE = 0.9       # cmd1 units / s
GRIP_OPEN = 0.70      # fully open
GRIP_CLOSE = -0.05    # fully closed

# Keep the commanded TCP inside a box around the neutral pose (metres).
BOX = np.array([0.55, 0.55, 0.45])


def rot_x(a): 
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


class Teleop:
    def __init__(self, render: bool = True, pad_index: int = 0,
                 view: ViewFlip | None = None, keyboard: bool = False,
                 env_index: int | None = None, agent: str | None = None,
                 addr: str | None = None):
        self.render = render
        # Optional viewpoint preset.  The default keeps the stock scheme.
        self.view = view if view is not None else parse_flags(False, False, False)
        self.view_saved = self.view
        # Scene targets are overridable from the CLI so the same folder can
        # be pointed at a differently-named robot or another scene index.
        rig_kw = {}
        if env_index is not None:
            rig_kw["env_index"] = env_index
        if agent:
            rig_kw["agent"] = agent
        if addr:
            rig_kw["addr"] = addr
        self.r = OrcaRig(**rig_kw)
        self.r.lock_base(settle_s=1.5)
        self.Rb = self.r.base_rot()
        # ---- 输入设备（手柄 / 键盘），二选一 --------------------
        # 两者接口完全一致，后续所有逻辑（left / right / lt / rt /
        # dpad / held / pressed / released）完全共用，因此只需在这里分流。
        if keyboard:
            from keypad import Keypad
            self.pad = Keypad()
        else:
            self.pad = Gamepad(index=pad_index)

        # Teleport both arms to the working pose, then let them settle.
        import mujoco
        for side in ("l", "r"):
            self.r.set_arm_qpos(side, NEUTRAL[side])
            self.r.set_gripper_qpos(side, self.r.table.spec(GRIP_OPEN))
        mujoco.mj_forward(self.r.m, self.r.d)
        for _ in range(60):
            self.r.step(self.r.ctrl(), 1, render=False)

        self.osc = {"l": OscArm(self.r, "l"), "r": OscArm(self.r, "r")}
        self.home_pose = {}
        for side in ("l", "r"):
            self.osc[side].hold()
            self.home_pose[side] = (self.osc[side].site_pos.copy(),
                                    self.osc[side].site_mat.copy())

        self.active = "r"          # start on the right arm
        self.goal = {s: list(self.home_pose[s]) for s in ("l", "r")}
        self.grip_cmd = {s: GRIP_OPEN for s in ("l", "r")}
        self._prev_dpad = (0, 0)
        self._prev_rstick = False
        print("control frame:", self.view.describe(), flush=True)

    # ------------------------------------------------------------- helpers
    def resync(self, side: str) -> None:
        self.goal[side] = [self.osc[side].site_pos.copy(),
                           self.osc[side].site_mat.copy()]

    def full_restart(self) -> None:
        """One-button do-over: put the scene and both arms back to the start."""
        import mujoco
        self.r.reset_objects()
        for side in ("l", "r"):
            self.r.set_arm_qpos(side, NEUTRAL[side])
            self.r.set_gripper_qpos(side, self.r.table.spec(GRIP_OPEN))
            self.grip_cmd[side] = GRIP_OPEN
        mujoco.mj_forward(self.r.m, self.r.d)
        for _ in range(80):
            self.r.step(self.r.ctrl(), 1, render=self.render)
        for side in ("l", "r"):
            self.osc[side].osc.update_initial_joints(
                np.asarray(self.r.d.qpos[self.r.arm_q[side]], float).copy())
            self.osc[side].hold()
            self.goal[side] = [self.osc[side].site_pos.copy(),
                               self.osc[side].site_mat.copy()]
        self.active = "r"
        print("RESTART: scene + arms + grippers reset", flush=True)

    def go_home(self, side: str) -> None:
        self.goal[side] = [self.home_pose[side][0].copy(),
                           self.home_pose[side][1].copy()]

    def nearest_object_side(self) -> str:
        """left object -> left arm, right object -> right arm (base-frame y)."""
        import mujoco
        best_side, best_d = None, 1e9
        for side in ("l", "r"):
            tcp = self.osc[side].pinch
            for i in range(self.r.m.nbody):
                nm = mujoco.mj_id2name(self.r.m, mujoco.mjtObj.mjOBJ_BODY, i) or ""
                if "Medical" in nm or "Basket_Wood" in nm:
                    d = float(np.linalg.norm(self.r.d.xpos[i] - tcp))
                    if d < best_d:
                        best_d = d
                        best_side = "l" if (self.Rb.T @ (self.r.d.xpos[i] - self.r.d.qpos[self.r.BQ:self.r.BQ+3]))[1] > 0 else "r"
        return best_side or "r"

    # ---------------------------------------------------------------- loop
    def run(self) -> None:
        dt = self.r.dt
        last = time.perf_counter()
        frame = 0
        print("teleop running. active arm =", self.active.upper(),
              " BACK=freeze, X=switch arm, Ctrl-C to stop", flush=True)
        try:
            while True:
                t0 = time.perf_counter()
                self.pad.poll()

                # ---- buttons
                if self.pad.pressed("BACK"):
                    pass
                if self.pad.pressed("X"):
                    self.active = select_arm(self.active, self.view)
                    note = ""
                    if self.view.mirrored:
                        from teleop_view import screen_side
                        note = "  (on screen: %s)" % screen_side(
                            self.active, self.view).upper()
                    print("active arm ->", self.active.upper() + note, flush=True)
                if self.pad.pressed("Y"):
                    self.go_home(self.active)
                    print("home", self.active.upper(), flush=True)
                if self.pad.pressed("START"):
                    self.resync(self.active)
                    print("resync", self.active.upper(), flush=True)
                if self.pad.dpad == (0, -1) and self._prev_dpad != (0, -1):
                    self.full_restart()
                self._prev_dpad = self.pad.dpad
                rst = self.pad.held("RSTICK")
                if rst and not self._prev_rstick:
                    stock = parse_flags(False, False, False)
                    self.view = stock if self.view.mirrored or self.view.flip_fb \
                        else self.view_saved
                    print("control frame ->", self.view.describe(), flush=True)
                self._prev_rstick = rst
                frozen = self.pad.held("BACK")

                # ---- gripper
                g = self.grip_cmd[self.active]
                if self.pad.held("A"):
                    g -= GRIP_RATE * dt
                if self.pad.held("B"):
                    g += GRIP_RATE * dt
                self.grip_cmd[self.active] = float(np.clip(g, GRIP_CLOSE, GRIP_OPEN))

                # ---- motion (base frame)
                side = self.active
                if not frozen:
                    lx, ly = self.pad.left
                    rx, ry = self.pad.right
                    lx, ly = self.view.apply(lx, ly)
                    # yaw is a horizontal rotation, so it mirrors with the view
                    # exactly like the left/right translation axis does.  Pitch
                    # and roll stay put.
                    if self.view.flip_lr:
                        rx = -rx
                    v = np.array([ly, lx, self.pad.rt - self.pad.lt]) * LIN_SPEED
                    v_base = np.array([v[0], v[1], v[2]])
                    self.goal[side][0] = self.goal[side][0] + self.Rb @ (v_base * dt)

                    w = np.array([rx, ry, self.pad.held("RB") - self.pad.held("LB")]) * ANG_SPEED
                    # The wrist rotates about the TOOL's own axes, not the
                    # world axes: right-multiplying keeps "push left -> turn
                    # left" true no matter how the hand is already oriented.
                    M = rot_z(w[0] * dt) @ rot_y(w[1] * dt) @ rot_x(w[2] * dt)
                    self.goal[side][1] = self.goal[side][1] @ M

                    # workspace clamp around the home pose
                    hp = self.home_pose[side][0]
                    d = self.goal[side][0] - hp
                    self.goal[side][0] = hp + np.clip(d, -BOX, BOX)

                # ---- apply
                self.osc[side].set_goal(self.goal[side][0], self.goal[side][1])
                c = self.r.ctrl()
                for s in ("l", "r"):
                    c = self._apply_osc(c, self.osc[s])
                c = self._apply_grip(c)
                self.r.step(c, 1, render=self.render)

                frame += 1
                if frame % 25 == 0:
                    now = time.perf_counter()
                    fps = 25.0 / max(1e-6, now - last)
                    last = now
                    pinch = self.osc[side].pinch
                    print(f"[{side.upper()}] pinch={np.round(pinch,3)} "
                          f"err={1000*self.osc[side].err_to(self.goal[side][0]):.1f}mm "
                          f"grip={self.grip_cmd[side]:+.2f} fps={fps:.1f}", flush=True)

                # pace to the control rate
                slack = dt - (time.perf_counter() - t0)
                if slack > 0:
                    time.sleep(slack)
        except KeyboardInterrupt:
            print("\nstopped", flush=True)
        finally:
            self.r.close()

    def _apply_osc(self, c, arm: OscArm):
        tau = arm.torques()
        for k, aid in enumerate(arm.AID):
            c[aid] = float(tau[k])
        return c

    def _apply_grip(self, c):
        for side in ("l", "r"):
            spec = self.r.table.spec(self.grip_cmd[side])
            for o, aid in self.r.ga[side].items():
                c[aid] = float(spec[o])
        return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--behind", action="store_true",
                    help="you watch the scene from the far side of the robot")
    ap.add_argument("--flip-lr", action="store_true",
                    help="mirror only the left/right stick axis")
    ap.add_argument("--flip-fb", action="store_true",
                    help="mirror only the forward/back stick axis")
    ap.add_argument("--view", default=None,
                    help="preset name: front | behind | flip-lr | flip-fb")
    ap.add_argument("--keyboard", action="store_true",
                    help="use the keyboard instead of a gamepad "
                         "(parallel fallback for machines without a pad)")
    ap.add_argument("--env-index", type=int, default=None,
                    help="simulation scene index (default: the built-in one)")
    ap.add_argument("--agent", default=None,
                    help="robot/agent name in the scene "
                         "(default: dual_arm_collaborative_service_robot_1)")
    ap.add_argument("--addr", default=None,
                    help="OrcaLab gRPC address (default: localhost:50051)")
    args = ap.parse_args()
    if args.view:
        from teleop_view import resolve
        view = resolve(args.view)
    else:
        view = parse_flags(args.behind, args.flip_lr, args.flip_fb)
    Teleop(render=not args.no_render, pad_index=args.index, view=view,
           keyboard=args.keyboard, env_index=args.env_index,
           agent=args.agent, addr=args.addr).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



