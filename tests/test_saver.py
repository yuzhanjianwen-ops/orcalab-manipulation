# -*- coding: utf-8 -*-
"""HDF5 落盘测试 + 往返读取校验。"""
import os, shutil, tempfile
import numpy as np
from recorder import Recorder, State
import saver_hdf5

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  PASS  " + name)
    else:    fail += 1; print("  FAIL  " + name + ("  " + str(extra) if extra else ""))

tmp = tempfile.mkdtemp(prefix="orca_ds_")
try:
    saver = saver_hdf5.Hdf5Saver(tmp, task_name="pick_medicine_box")
    rec = Recorder()
    rec.set_saver(saver)
    rec.arm(); rec.toggle_record()
    for i in range(20):
        rec.capture({
            "timestamp": np.float32(i * 0.04),
            "joint_pos": np.arange(14, dtype=np.float32) + i,
            "ee_pos": np.array([1.7, -3.1, 1.4 + i*0.01], np.float32),
            "action_pos": np.array([1.7, -3.1, 1.5], np.float32),
            "image": (np.zeros((8, 8, 3), np.uint8) + i),
        })
    rec.toggle_record()
    rec.save()

    check("落盘 1 条", saver.n_saved == 1, saver.n_saved)
    p = saver.saved[0]
    check("文件存在", os.path.exists(p), p)

    import h5py
    with h5py.File(p, "r") as f:
        check("observations/joint_pos 形状", f["observations/joint_pos"].shape == (20, 14),
              f["observations/joint_pos"].shape)
        check("observations/image 形状", f["observations/image"].shape == (20, 8, 8, 3),
              f["observations/image"].shape)
        check("actions/pos 形状", f["actions/pos"].shape == (20, 3), f["actions/pos"].shape)
        check("timestamp 形状", f["timestamp"].shape == (20,), f["timestamp"].shape)
        check("n_frames 属性", f.attrs["n_frames"] == 20, f.attrs["n_frames"])
        check("task_name 属性", f.attrs["task_name"] == "pick_medicine_box")
        check("success 属性", bool(f.attrs["success"]) is True)
        jp = f["observations/joint_pos"][:]
        check("数据内容正确", np.allclose(jp[5], np.arange(14) + 5), jp[5][:3])
        im = f["observations/image"][:]
        check("图像内容正确", im[7][0, 0, 0] == 7, im[7][0, 0, 0])

    # meta.json
    import json
    mp = os.path.join(os.path.dirname(p), "meta.json")
    check("meta.json 存在", os.path.exists(mp))
    meta = json.load(open(mp, encoding="utf-8"))
    check("meta 帧数", meta["n_frames"] == 20, meta["n_frames"])
    check("meta 字段表", "joint_pos" in meta["fields"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=" * 52)
print(f"结果: {ok} passed, {fail} failed")
