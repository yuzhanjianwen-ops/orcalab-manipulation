# -*- coding: utf-8 -*-
"""诊断：读取活模型里 药瓶/药盒/夹爪/桌面 的接触参数。

输出：friction、condim、solref、solimp、geom 类型尺寸。
用于确定「药瓶被抬起时滑脱」该调哪个参数。
"""
import os, sys, io
# 本文件位于 tests/，操作模块在 scripts/teleop
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "scripts", "teleop")
sys.path.insert(0, HERE)
os.chdir(HERE)

import numpy as np
import mujoco
from orca_rig import OrcaRig

OUT = io.open("diag_contact.txt", "w", encoding="utf-8")
def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    OUT.write(line + "\n"); OUT.flush()

r = OrcaRig()
log("ngeom =", r.m.ngeom)
log()

def body_of(g):
    return mujoco.mj_id2name(r.m, mujoco.mjtObj.mjOBJ_BODY,
                             int(r.m.geom_bodyid[g])) or "?"

def gname(g):
    return mujoco.mj_id2name(r.m, mujoco.mjtObj.mjOBJ_GEOM, g) or "?"

log("=" * 100)
log("按 body 名分类扫描全部 geom（关注 药瓶/药盒/夹爪/桌面/垫布）")
log("=" * 100)
log("%-4s %-38s %-22s %-6s %-30s %-4s %-22s %-30s" % (
    "id", "body", "geom", "type", "friction(sliding)", "cdim", "solref", "solimp"))
log("-" * 100)

KEY = ("vial", "bottle", "medicine", "medical", "basket", "box", "bottle",
       "gripper", "hand", "finger", "pad", "table", "cushion", "cloth",
       "mat", "药", "瓶", "盒")
for g in range(r.m.ngeom):
    b = body_of(g); n = gname(g)
    hay = (b + " " + n).lower()
    if any(k.lower() in hay for k in KEY):
        log("%-4d %-38s %-22s %-6d %-30s %-4d %-22s %-30s" % (
            g, b[:38], n[:22], int(r.m.geom_type[g]),
            np.round(r.m.geom_friction[g], 4), int(r.m.geom_condim[g]),
            np.round(r.m.geom_solref[g], 4), np.round(r.m.geom_solimp[g], 4)))

log()
log("=" * 100)
log("半径/尺寸较大的可抓物体（可能是药瓶/药盒）")
log("=" * 100)
for g in range(r.m.ngeom):
    b = body_of(g)
    sz = r.m.geom_size[g]
    if int(r.m.geom_type[g]) in (2, 4, 5) and float(np.max(sz)) > 0.015:
        if any(k in b.lower() for k in ("vial", "bottle", "medicine", "box", "basket", "medical")):
            log("  geom %d  body=%-40s type=%d size=%s condim=%d fric=%s" % (
                g, b[:40], int(r.m.geom_type[g]), np.round(sz, 4),
                int(r.m.geom_condim[g]), np.round(r.m.geom_friction[g], 4)))

log()
log("=" * 100)
log("夹爪指垫（真正参与抓握的 geom）")
log("=" * 100)
for g in range(r.m.ngeom):
    b = body_of(g)
    if "gripper" in b.lower():
        log("  geom %d  body=%-40s type=%d size=%s condim=%d fric=%s solref=%s solimp=%s" % (
            g, b[:40], int(r.m.geom_type[g]), np.round(r.m.geom_size[g], 4),
            int(r.m.geom_condim[g]), np.round(r.m.geom_friction[g], 4),
            np.round(r.m.geom_solref[g], 4), np.round(r.m.geom_solimp[g], 4)))

log()
log("=" * 100)
log("默认值（用于对比：未显式设置的 geom 会用这些）")
log("=" * 100)
log("  m.opt.o_friction =", np.round(r.m.opt.o_friction, 4))
log("  m.opt.o_solref   =", np.round(r.m.opt.o_solref, 4))
log("  m.opt.o_solimp   =", np.round(r.m.opt.o_solimp, 4))
log("  m.opt.o_condim   =", int(r.m.opt.o_condim))
log("  timestep         =", r.m.opt.timestep)
log("  gravity          =", np.round(r.m.opt.gravity, 4))

r.close(); OUT.close()
print("\n>> 结果已写入 diag_contact.txt")
