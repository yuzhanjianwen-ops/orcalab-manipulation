# -*- coding: utf-8 -*-
"""可移植版：夹取摩擦参数对比实验（自包含，不依赖任何外部文件）。

用途：回答「药瓶抓住后抬起滑脱，该调哪个参数」。
搭建两指夹爪夹住圆柱再上抬的最小模型，比较 condim / friction /
solref / solimp 对相对滑脱量的影响。

运行：
    python exp_friction_study.py
"""
import mujoco

XML = """
<mujoco>
  <option timestep="0.001" gravity="0 0 -9.81" iterations="100"
          noslip_iterations="20"/>
  <worldbody>
    <geom name="floor" type="plane" size="2 2 0.1"
          friction="1 0.005 0.0001"/>
    <body name="vial" pos="0 0 0.10">
      <joint type="free"/>
      <geom name="vial" type="cylinder" size="0.012 0.035" mass="0.05"
            friction="{f}" condim="{cd}" solref="{sr}" solimp="{si}"/>
    </body>
    <body name="pad_l" pos="-0.020 0 0.10">
      <joint name="jl" type="slide" axis="1 0 0"/>
      <joint name="jzl" type="slide" axis="0 0 1"/>
      <geom name="pad_l" type="box" size="0.006 0.02 0.03" mass="0.3"
            friction="{f}" condim="{cd}" solref="{sr}" solimp="{si}"/>
    </body>
    <body name="pad_r" pos="0.020 0 0.10">
      <joint name="jr" type="slide" axis="1 0 0"/>
      <joint name="jzr" type="slide" axis="0 0 1"/>
      <geom name="pad_r" type="box" size="0.006 0.02 0.03" mass="0.3"
            friction="{f}" condim="{cd}" solref="{sr}" solimp="{si}"/>
    </body>
  </worldbody>
  <actuator>
    <position joint="jl"  kp="{kp}" kv="4"/>
    <position joint="jzl" kp="3000" kv="80"/>
    <position joint="jr"  kp="{kp}" kv="4"/>
    <position joint="jzr" kp="3000" kv="80"/>
  </actuator>
</mujoco>
"""

VIAL, PAD_L, PAD_R = 1, 2, 3


def run(f="1 0.005 0.0001", cd=3, sr="0.02 1", si="0.9 0.95 0.001",
        gap=0.0225, rise=0.05, t_rise=0.8, kp=60):
    """返回 (相对滑脱 mm, 药瓶实际上升 mm)。

    gap 接近药瓶直径(24mm) -> 夹紧力弱 -> 处于滑脱临界，
    这样参数差异才会显现（对应「抓住后抬起会滑出去」的现象）。
    """
    xml = XML.format(f=f, cd=cd, sr=sr, si=si, kp=kp)
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)

    half = gap / 2.0
    tgt_l = -half + 0.020
    tgt_r = half - 0.020

    for _ in range(2000):
        d.ctrl[0] = tgt_l; d.ctrl[1] = 0.0
        d.ctrl[2] = tgt_r; d.ctrl[3] = 0.0
        mujoco.mj_step(m, d)

    if d.ncon == 0:
        return None, None

    z_pad0 = float(d.xpos[PAD_L][2])
    z_v0 = float(d.xpos[VIAL][2])
    rel0 = z_v0 - z_pad0

    n = int(t_rise / m.opt.timestep)
    for k in range(n):
        h = rise * (k + 1) / n
        d.ctrl[0] = tgt_l; d.ctrl[1] = h
        d.ctrl[2] = tgt_r; d.ctrl[3] = h
        mujoco.mj_step(m, d)

    rel1 = float(d.xpos[VIAL][2]) - float(d.xpos[PAD_L][2])
    return (rel0 - rel1) * 1000, (float(d.xpos[VIAL][2]) - z_v0) * 1000


if __name__ == "__main__":
    print("弱夹紧(gap=22.5mm) -> 处于滑脱临界，最能区分参数")
    print("滑脱 = 药瓶相对夹爪下滑量（越小越好）")
    print("=" * 74)
    print("%-32s %14s %16s" % ("参数", "相对滑脱(mm)", "药瓶升(mm)"))
    print("-" * 74)

    cases = [
        ("condim=3, slide=1.0 (基准)", dict()),
        ("condim=4, slide=1.0", dict(cd=4)),
        ("condim=6, slide=1.0", dict(cd=6)),
        ("condim=3, slide=2.5", dict(f="2.5 0.005 0.0001")),
        ("condim=3, slide=4.0", dict(f="4.0 0.005 0.0001")),
        ("condim=6, slide=2.5 spin=0.5 roll=0.05",
         dict(cd=6, f="2.5 0.5 0.05")),
        ("solref=0.002 1", dict(sr="0.002 1")),
        ("solimp=0.95 0.99 0.001", dict(si="0.95 0.99 0.001")),
        ("推荐组合: condim=3 slide=2.5 sr=0.002",
         dict(f="2.5 0.005 0.0001", sr="0.002 1")),
    ]
    for name, kw in cases:
        s, v = run(**kw)
        if s is None:
            print("%-32s %14s %16s" % (name, "未接触", "-"))
        else:
            print("%-32s %14.3f %16.3f" % (name, s, v))

    print()
    print("多夹紧强度下的稳健性检查（滑脱 mm）")
    print("=" * 74)
    print("%-32s %10s %10s %10s" % ("参数", "kp=40", "kp=100", "kp=200"))
    print("-" * 74)
    for name, kw in cases:
        cells = []
        for kp in (40, 100, 200):
            s, _ = run(kp=kp, **kw)
            cells.append("%10.2f" % s if s is not None else "%10s" % "-")
        print("%-32s %s" % (name, " ".join(cells)))
