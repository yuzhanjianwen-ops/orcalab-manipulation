# -*- coding: utf-8 -*-
"""沙箱可用的 orca_gym 引导模块 (bootstrap shim)。

背景
----
orca_gym 在 import 时会初始化一个全局日志器，把文件写到
    <site-packages>/logs/orca_gym.log
该路径由 orca_log.py 内部硬算（PROJECT_ROOT），而该文件属于本机用户账号，
沙箱账号只读 —— 于是 `import orca_gym` 直接 PermissionError 崩掉。

本模块的做法：在 import orca_gym 之前，劫持
`logging.handlers.RotatingFileHandler`，把所有文件写入重定向到可写目录。
这样既不修改 site-packages 里的任何文件，也不影响真实用户运行时
（真实用户直接 import orca_gym 不受影响，因为本模块只在采集脚本里被显式导入）。

用法
----
**必须在 import orca_gym 之前导入本模块：**

    import orca_boot          # noqa: F401  <- 必须放在最前面
    from orca_gym.sensor.rgbd_camera import CameraWrapper

也建议设置 matplotlib 缓存目录，避免同样因为只读路径产生的警告。
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# --------------------------------------------------------------------------
# 1. 选择可写目录
# --------------------------------------------------------------------------
# 优先级：环境变量 ORCA_SANDBOX_LOG_DIR > 调用方当前目录下的 .orca_logs
_ENV_KEY = "ORCA_SANDBOX_LOG_DIR"
LOG_DIR = os.environ.get(_ENV_KEY) or os.path.join(os.getcwd(), ".orca_logs")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError:
    import tempfile

    LOG_DIR = os.path.join(tempfile.gettempdir(), "orca_logs")
    os.makedirs(LOG_DIR, exist_ok=True)

os.environ.setdefault(_ENV_KEY, LOG_DIR)

# matplotlib 默认把缓存写到 ~/.matplotlib，沙箱同样不可写 —— 一并重定向。
os.environ.setdefault("MPLCONFIGDIR", os.path.join(LOG_DIR, "mpl"))

# --------------------------------------------------------------------------
# 2. 劫持 RotatingFileHandler
# --------------------------------------------------------------------------
_ORIG_RFH = RotatingFileHandler
_REDIRECTS: dict[str, str] = {}


def _redirecting_handler(filename, *args, **kwargs):
    """把任何日志文件重定向到可写目录，保持文件名不变。"""
    base = os.path.basename(str(filename))
    target = os.path.join(LOG_DIR, base)
    _REDIRECTS[str(filename)] = target
    return _ORIG_RFH(target, *args, **kwargs)


logging.handlers.RotatingFileHandler = _redirecting_handler

# orca_log.py 内部写的是 `from logging.handlers import RotatingFileHandler`，
# 即模块级已绑定了原函数。所以 import 之后还要把它模块内的引用也换掉。
try:
    import orca_gym.log.orca_log as _ol  # noqa: E402

    _ol.RotatingFileHandler = _redirecting_handler
except Exception:  # pragma: no cover - 允许在没有 orca_gym 的机器上导入本模块
    pass


def redirect_report() -> dict:
    """返回 {原始路径: 实际写入路径}，用于排查。"""
    return dict(_REDIRECTS)


def log_dir() -> str:
    """当前日志目录。"""
    return LOG_DIR
