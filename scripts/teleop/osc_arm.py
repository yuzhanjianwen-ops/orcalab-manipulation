# -*- coding: utf-8 -*-
"""Side-aware Operational Space Control (OSC_POSE) wrapper for one arm.

Algorithm from the client repo (OrcaManipulation, dev_g1_omnipicker):
    create_arm_osc_controller -> robosuite OSC_POSE (kp=150, damping_ratio=1)

The controller tracks the absolute pose of the arm's `ee_center_site_<side>`.
Torques come back gravity-compensated and are written straight into the seven
`_mctrl` torque actuators, so there is no IK and no hand-tuned joint PD.
"""
from __future__ import annotations

import numpy as np

# orca_rig installs the logging / XML-lock shims as an import side effect; it
# must be imported before any orca_gym module that touches those helpers.
from orca_rig import _install_orca_shims
_install_orca_shims()

from orca_gym.adapters.robosuite.controllers import (  # noqa: E402
    controller_config,
    controller_factory,
)

# Grasp point offset from the ee_center site, along the gripper approach axis.
TCP_LOCAL = np.array([0.112, 0.0, 0.0015])


class OscArm:
    def __init__(self, rig, side: str, kp: float = 150.0,
                 damping_ratio: float = 1.0):
        assert side in ("l", "r")
        self.r = rig
        self.side = side
        env = rig.u
        self.jnames = list(rig.arm[side])
        qo, vo, _ = env.query_joint_offsets(self.jnames)
        self.AID = list(rig.arm_a[side])
        self.LIM = [np.asarray(rig.acts[j + "_mctrl"]["CtrlRange"], float).flatten()
                    for j in self.jnames]
        lo = [float(l[0]) for l in self.LIM]
        hi = [float(l[1]) for l in self.LIM]
        cfg = controller_config.load_config("osc_pose")
        cfg.update({
            "sim": rig.u.gym,
            "eef_name": env.site(f"ee_center_site_{side}"),
            "joint_indexes": {"joints": self.jnames, "qpos": qo, "qvel": vo},
            "actuator_range": [lo, hi],
            "kp": kp,
            "damping_ratio": damping_ratio,
            "policy_freq": 1.0 / rig.dt,
            "ndim": 7,
            "control_delta": False,   # we command absolute goals
        })
        self.osc = controller_factory(cfg["type"], cfg)
        self.osc.update_initial_joints(np.asarray(rig.d.qpos[rig.arm_q[side]], float).copy())
        self.goal_pos = self.osc.ee_pos.copy()
        self.goal_mat = self.osc.ee_ori_mat.copy()
        self.nstep = 0
        self.nsat = 0

    # -------------------------------------------------------------- queries
    @property
    def site_pos(self):
        return self.osc.ee_pos.copy()

    @property
    def site_mat(self):
        return self.osc.ee_ori_mat.copy()

    @property
    def pinch(self):
        return self.osc.ee_pos + self.osc.ee_ori_mat @ TCP_LOCAL

    def err_to(self, site_pos) -> float:
        return float(np.linalg.norm(self.osc.ee_pos - np.asarray(site_pos, float)))

    # -------------------------------------------------------------- control
    def set_goal(self, site_pos, mat) -> None:
        """Absolute goal; set_pos/set_ori bypass the delta parsing entirely."""
        self.goal_pos = np.asarray(site_pos, float).copy()
        self.goal_mat = np.asarray(mat, float).copy()
        self.osc.set_goal(np.zeros(6), set_pos=self.goal_pos, set_ori=self.goal_mat)

    def hold(self) -> None:
        self.osc.set_goal(np.zeros(6), set_pos=self.goal_pos, set_ori=self.goal_mat)

    def torques(self) -> np.ndarray:
        tau = self.osc.run_controller()
        self.nstep += 1
        for k, l in enumerate(self.LIM):
            if tau[k] < l[0] or tau[k] > l[1]:
                self.nsat += 1
        return tau
