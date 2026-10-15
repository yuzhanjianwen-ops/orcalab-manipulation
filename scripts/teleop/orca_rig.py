# -*- coding: utf-8 -*-
"""Side-aware rig for the OrcaLab dual-arm robot (teleop foundation).

A cleaned-up, *both-arms* version of the legacy `work/rig.py`.  It owns the
connection to the running OrcaLab simulation, the base lock, the dynamics
tuning, the two arms and the two four-bar grippers.

Everything is side-agnostic: `side="l"` or `side="r"`.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from contextlib import asynccontextmanager

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# numba's on-disk JIT cache cannot write into the read-only site-packages tree
# in this sandbox, which makes `import controller_factory` hang forever.  Point
# the cache at a writable directory.  Must be set before numba is imported.
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(HERE, ".numba_cache"))

# 本目录即操作模块的根：所有资源都放在本文件夹内，
# 因此整个文件夹可以直接拷到其它电脑使用（自包含）。
ASSETS_DIR = os.path.join(HERE, "assets")


def _install_orca_shims() -> None:
    """Neutralise two OrcaGym helpers that cannot run in this sandbox.

    * the rotating file logger cannot open its log file;
    * the Windows XML cache lock cannot create a sibling `.lock`.
    The teleop client only reads the cached model, so both writes are skipped.
    Must run before orca_gym.core is imported by anything else.
    """
    class _StreamOnly(logging.StreamHandler):
        def __init__(self, *a, **k):
            super().__init__()

    logging.handlers.RotatingFileHandler = _StreamOnly

    import orca_gym.core.orca_gym_local as local_core

    @asynccontextmanager
    async def _cached_xml_lock(*_args, **_kwargs):
        yield

    local_core.file_lock = _cached_xml_lock


_install_orca_shims()

import gymnasium as gym  # noqa: E402
from orca_gym.scripts.run_sim_loop import register_env  # noqa: E402

AGENT = "dual_arm_collaborative_service_robot_1"
ORCAGYM_ADDR = "localhost:50051"

GORDER = ["inner_joint1", "inner_joint2", "inner_joint3", "inner_joint4",
          "outer_joint1", "outer_joint2", "outer_joint3", "outer_joint4"]
GDRIVEN = ("inner_joint1", "outer_joint1")

NEUTRAL = {
    "l": np.array([-1.42, 0.88, 1.54, -1.48, 0.0, 0.0, 0.0]),
    "r": np.array([1.42, -0.88, -1.54, 1.48, 0.0, 0.0, 0.0]),
}

GRIPPER_TABLE_PATH = os.path.join(ASSETS_DIR, "gripper_table.json")
# 兼容：如果 assets/ 下没有，再退回本目录根
if not os.path.exists(GRIPPER_TABLE_PATH):
    GRIPPER_TABLE_PATH = os.path.join(HERE, "gripper_table.json")


class GripperTable:
    """cmd1 (joint1 command) -> eight gripper joint positions.

    cmd1 = +0.70 -> fully open (~126.7 mm between the finger pads)
    cmd1 = -0.05 -> closed    (~0.3 mm)
    """

    def __init__(self, path: str = GRIPPER_TABLE_PATH):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.cmd = np.asarray(raw["cmd1"], dtype=float)
        self.q = np.asarray(raw["table"], dtype=float)  # (45, 8)
        self.lo = float(self.cmd[0])
        self.hi = float(self.cmd[-1])

    def spec(self, cmd1: float) -> dict[str, float]:
        cmd1 = float(np.clip(cmd1, self.lo, self.hi))
        row = np.array([np.interp(cmd1, self.cmd, self.q[:, i])
                        for i in range(self.q.shape[1])])
        return {o: float(row[i]) for i, o in enumerate(GORDER)}


class OrcaRig:
    """Live connection to the OrcaLab simulation, side-aware for both arms."""

    DAMP, ARMAT = 5.0, 0.20
    KP, KD = 110.0, 9.0

    def __init__(self, env_index: int = 93, agent: str = AGENT,
                 addr: str = ORCAGYM_ADDR):
        env_id, _ = register_env(addr, "SimulationLoop", env_index, agent,
                                 sys.maxsize)
        self.env = gym.make(env_id)
        u = self.env.unwrapped
        self.u = u
        self.env.reset()
        u.gym.update_data()
        self.m = u.gym._mjModel
        self.d = u.gym._mjData
        self.joints = u.model.get_joint_dict()
        self.acts = u.model.get_actuator_dict()
        self.bodies = u.model.get_body_dict()
        self.dt = float(u.dt)
        self.agent = agent

        self.arm, self.arm_q, self.arm_v, self.arm_a, self.site = {}, {}, {}, {}, {}
        self.gj, self.gq, self.ga = {}, {}, {}
        for side in ("l", "r"):
            self._index_arm(side)
            self._index_gripper(side)

        self._enable_torque_limits()

        self.BQ = self.BV = None
        for nm, j in self.joints.items():
            if nm.endswith("free_joint") and agent in nm:
                self.BQ = int(j["QposIdxStart"])
                self.BV = int(j["QvelIdxStart"])
        self.base0 = None
        self.hold_base = False

        import mujoco

        # Free-joint movable scene objects (medication box / bottle / tray).
        # Snapshot them at connect time so a "reset" can restore the scene.
        self.obj_q = []   # list of (qposadr, qveladr)
        for i in range(self.m.njnt):
            if int(self.m.jnt_type[i]) != 0:      # 0 == mjJNT_FREE
                continue
            jname = mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_JOINT, i) or ""
            if "ActorManipulator" in jname or "Anchor" in jname:
                continue                          # scene-manipulation helpers
            jn = self.joints.get(jname, {})
            if jn.get("QposIdxStart") == self.BQ:
                continue                          # that is the robot base
            self.obj_q.append((int(self.m.jnt_qposadr[i]),
                               int(self.m.jnt_dofadr[i])))
        self.obj_init = [self.d.qpos[a:a + 7].copy() for a, _ in self.obj_q]
        self.table = GripperTable()
        self._tune_gripper()
        self.tune_dynamics()

    # ------------------------------------------------------------ indexing
    def _index_arm(self, side: str) -> None:
        import mujoco
        names = []
        for k in range(1, 8):
            cands = sorted(n for n in self.joints if f"arm_{side}_joint{k}" in n)
            if not cands:
                raise RuntimeError(f"missing arm_{side}_joint{k}")
            names.append(cands[0])
        self.arm[side] = names
        self.arm_q[side] = np.array([int(self.joints[n]["QposIdxStart"]) for n in names])
        self.arm_v[side] = np.array([int(self.joints[n]["QvelIdxStart"]) for n in names])
        self.arm_a[side] = [int(self.acts[n + "_mctrl"]["ActuatorId"]) for n in names]
        self.site[side] = mujoco.mj_name2id(
            self.m, mujoco.mjtObj.mjOBJ_SITE, f"{self.agent}_ee_center_site_{side}")

    def _index_gripper(self, side: str) -> None:
        gj, gq, ga = {}, {}, {}
        for o in GORDER:
            cands = sorted(n for n in self.joints
                           if n.endswith(o) and f"gripper_{side}" in n)
            if not cands:
                raise RuntimeError(f"missing gripper_{side} {o}")
            gj[o] = cands[0]
            gq[o] = int(self.joints[cands[0]]["QposIdxStart"])
            act = [k for k in self.acts if cands[0] in k and k.endswith("_pctrl")]
            if not act:
                raise RuntimeError(f"missing actuator for {cands[0]}")
            ga[o] = int(self.acts[act[0]]["ActuatorId"])
        self.gj[side], self.gq[side], self.ga[side] = gj, gq, ga

    def _enable_torque_limits(self) -> None:
        for side in ("l", "r"):
            for i, aid in enumerate(self.arm_a[side]):
                limit = 60.0 if i < 4 else 30.0
                self.m.actuator_forcelimited[aid] = 1
                self.m.actuator_forcerange[aid] = [-limit, limit]

    def _tune_gripper(self) -> None:
        for side in ("l", "r"):
            for o in GORDER:
                a = self.ga[side][o]
                self.m.actuator_gainprm[a, 0] = 400.0
                self.m.actuator_biasprm[a, 1] = -400.0
                self.m.actuator_biasprm[a, 0] = 0.0

    def tune_dynamics(self, damp=None, armat=None) -> None:
        """Raise damping / armature so the 50 Hz torque loop stays stable."""
        import mujoco
        damp = self.DAMP if damp is None else damp
        armat = self.ARMAT if armat is None else armat
        FREE = mujoco.mjtJoint.mjJNT_FREE
        BALL = mujoco.mjtJoint.mjJNT_BALL
        for i in range(self.m.njnt):
            t = self.m.jnt_type[i]
            if t == FREE:
                continue
            w = 3 if t == BALL else 1
            va = int(self.m.jnt_dofadr[i])
            for k in range(w):
                self.m.dof_damping[va + k] = max(float(self.m.dof_damping[va + k]), damp)
                self.m.dof_armature[va + k] = max(float(self.m.dof_armature[va + k]), armat)

    # ---------------------------------------------------------------- state
    def arm_qpos(self, side: str) -> np.ndarray:
        return self.d.qpos[self.arm_q[side]].copy()

    def set_arm_qpos(self, side: str, q) -> None:
        self.d.qpos[self.arm_q[side]] = np.asarray(q, float)

    def gripper_qpos(self, side: str) -> dict[str, float]:
        return {o: float(self.d.qpos[self.gq[side][o]]) for o in GORDER}

    def set_gripper_qpos(self, side: str, spec: dict[str, float]) -> None:
        for o in GORDER:
            self.d.qpos[self.gq[side][o]] = float(spec[o])

    def site_pos_mat(self, side: str):
        import mujoco
        mujoco.mj_forward(self.m, self.d)
        R = self.d.site_xmat[self.site[side]].reshape(3, 3).copy()
        return self.d.site_xpos[self.site[side]].copy(), R

    def base_rot(self):
        """3x3 rotation of the floating base (world <- base)."""
        from scipy.spatial.transform import Rotation as Rot
        w, x, y, z = self.d.qpos[self.BQ + 3:self.BQ + 7]
        return Rot.from_quat([x, y, z, w]).as_matrix()

    # --------------------------------------------------------------- control
    def ctrl(self, arm_targets: dict | None = None,
             grip_specs: dict | None = None) -> np.ndarray:
        """Build the full control vector.

        arm_targets : {side: q7}  joint-space PD targets (gravity-compensated)
        grip_specs  : {side: {joint: value}}  eight-joint four-bar command
        Anything not supplied simply holds its current position.
        """
        arm_targets = arm_targets or {}
        grip_specs = grip_specs or {}
        ctrl = np.zeros(self.m.nu)
        for nm, a in self.acts.items():
            j = a["JointName"]
            aid = int(a["ActuatorId"])
            qa = int(self.joints[j]["QposIdxStart"])
            va = int(self.joints[j]["QvelIdxStart"])
            if "wheel" in j:
                ctrl[aid] = 0.0
            elif nm.endswith("_mctrl"):
                side = self._side_of_arm_joint(j)
                if side is not None and side in arm_targets:
                    i = self.arm[side].index(j)
                    qtar = float(arm_targets[side][i])
                    ctrl[aid] = self.d.qfrc_bias[va] + self.KP * (qtar - self.d.qpos[qa]) - self.KD * self.d.qvel[va]
                else:
                    ctrl[aid] = self.d.qfrc_bias[va] - self.KD * self.d.qvel[va]
            else:
                side = self._side_of_gripper_joint(j)
                if side is not None and side in grip_specs:
                    o = next(k for k, v in self.gj[side].items() if v == j)
                    ctrl[aid] = float(grip_specs[side].get(o, self.d.qpos[qa]))
                else:
                    ctrl[aid] = float(self.d.qpos[qa])
            cr = np.asarray(a["CtrlRange"], dtype=float).flatten()
            if cr.size == 2:
                ctrl[aid] = float(np.clip(ctrl[aid], cr[0], cr[1]))
        return ctrl

    def _side_of_arm_joint(self, j: str):
        for side in ("l", "r"):
            if j in self.arm[side]:
                return side
        return None

    def _side_of_gripper_joint(self, j: str):
        for side in ("l", "r"):
            if j in self.gj[side].values():
                return side
        return None

    def step(self, ctrl, n: int = 1, render: bool = True) -> None:
        for _ in range(n):
            self._hold()
            self.u.set_ctrl(ctrl)
            self.u.do_simulation(ctrl, self.u.frame_skip)
            self._hold()
            if render:
                self.u.render()

    def ramp_arms(self, targets: dict, secs: float = 2.0,
                  grip_specs: dict | None = None, render: bool = True) -> None:
        """Smoothstep both arms from their current pose to `targets`."""
        start = {s: self.arm_qpos(s) for s in targets}
        n = max(2, int(secs / self.dt))
        for i in range(n):
            k = (i + 1) / n
            k = k * k * (3 - 2 * k)
            cmd = {s: start[s] + (np.asarray(targets[s], float) - start[s]) * k
                   for s in targets}
            self.step(self.ctrl(cmd, grip_specs), 1, render)

    # ---------------------------------------------------------------- base
    def lock_base(self, settle_s: float = 1.5) -> np.ndarray:
        """Let the robot settle onto the ground, then pin the floating base."""
        self.hold_base = False
        if settle_s > 0:
            for _ in range(max(1, int(settle_s / self.dt))):
                self.step(self.ctrl(), render=False)
        self.base0 = self.d.qpos[self.BQ:self.BQ + 7].copy()
        self.hold_base = True
        return self.base0

    def _hold(self) -> None:
        if self.hold_base:
            self.d.qpos[self.BQ:self.BQ + 7] = self.base0
            self.d.qvel[self.BV:self.BV + 6] = 0.0

    def unlock_base(self) -> None:
        self.hold_base = False

    # ---------------------------------------------------------------- scene
    def reset_objects(self) -> None:
        """Restore every movable scene object to its connect-time pose."""
        for (qa, va), q0 in zip(self.obj_q, self.obj_init):
            self.d.qpos[qa:qa + 7] = q0
            self.d.qvel[va:va + 6] = 0.0

    def n_objects(self) -> int:
        return len(self.obj_q)
    def close(self) -> None:
        try:
            self.env.close()
        except Exception:
            pass








