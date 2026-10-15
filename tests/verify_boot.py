# -*- coding: utf-8 -*-
import sys, os
# 本文件位于 tests/，orca_boot 在 scripts/collect
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts", "collect"))

import orca_boot                      # noqa: F401  必须最先导入
print("log_dir:", orca_boot.log_dir())

from orca_gym.sensor.rgbd_camera import CameraWrapper
from orca_gym.log.orca_log import get_orca_logger

lg = get_orca_logger()
lg.info("bootstrap shim 验证")

c = CameraWrapper("probe", 8765)
print("CameraWrapper OK, port =", c.port, "| first_frame =", c.is_first_frame_received())
print("重定向表:", orca_boot.redirect_report())
print()
print("目录内容:", sorted(os.listdir(orca_boot.log_dir())))
