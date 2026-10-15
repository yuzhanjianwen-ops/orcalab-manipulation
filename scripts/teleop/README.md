# 双臂遥操作模块（手柄 / 键盘）

OrcaLab 双臂服务机器人的**遥操作**子系统。两套输入设备并行支持：

- **手柄**（XInput，Flydigi Vader 5 Pro 等）— 主用，手感好
- **键盘**（全局键状态）— 备选，适合没有手柄的线下同学

两者接口完全一致，共用同一套运动控制逻辑，启动时二选一。

---

## 一、快速开始

```powershell
# 手柄（默认）
python -X utf8 -u teleop.py --flip-lr

# 键盘
python -X utf8 -u teleop.py --keyboard --flip-lr
```

> `--flip-lr`：相机在机器人背后时使用（镜像左右轴）

---

## 二、目录结构

```
teleop/
├── teleop.py              # 主程序：控制循环、输入处理、运动解算
├── orca_rig.py            # 机器人装置：连接仿真、底座锁定、双臂与夹爪
├── osc_arm.py             # OSC 末端控制器封装（甲方 OrcaGym 提供）
├── gamepad.py             # 手柄驱动（纯 ctypes XInput，无需 pygame）
├── keypad.py              # 键盘驱动（GetAsyncKeyState，不受焦点影响）
├── teleop_view.py         # 视角/镜像配置（前后左右翻转）
│
├── assets/
│   └── gripper_table.json # 夹爪 cmd -> 8 个关节位置的标定表
│
├── docs/
│   ├── 手柄说明书.md              # 手柄键位与操作说明
│   ├── 键盘操作使用说明书.md      # 键盘键位与操作说明
│   ├── 键盘驱动说明.md            # 键盘驱动的设计/踩坑记录
│   ├── PRESET.md                  # 视角预设
│   └── 手腕姿态方向问题分析与修复.md
│
├── tests/
│   ├── test_keypad.py                    # 键盘单元测试（54 项）
│   ├── test_keypad_realtime.py           # 键盘真机语义自检
│   ├── test_teleop_keyboard_integration.py  # 端到端联调（21 项）
│   ├── exp_friction_study.py             # 摩擦/接触参数对比实验
│   └── diag_contact.py                   # 读取仿真实体接触参数
│
├── backup/                # 历史版本（回退用）
├── requirements.txt
└── README.md
```

---

## 三、文件职责

| 文件 | 作用 | 关键点 |
|---|---|---|
| `teleop.py` | 主循环 | `--keyboard` 在此分流；其余逻辑手柄/键盘共用 |
| `orca_rig.py` | 装置层 | 依赖 `mujoco` / `orca_gym`；读 `assets/gripper_table.json` |
| `osc_arm.py` | 控制器 | OSC_POSE（来自甲方 OrcaGym） |
| `gamepad.py` | 手柄输入 | 纯 `ctypes` 调 `XInputGetState` |
| `keypad.py` | 键盘输入 | `GetAsyncKeyState`，**不受窗口焦点影响** |
| `teleop_view.py` | 视角 | 左右/前后镜像 |

---

## 四、运行依赖

### 必须
| 依赖 | 说明 |
|---|---|
| Python 3.11 | 与 `orcalab` conda 环境一致 |
| `numpy` | 数值计算 |
| `scipy` | 姿态/旋转变换 |
| **OrcaLab 仿真端** | 机器人模型与物理仿真（`localhost:50051`）|
| **`orca_gym`** | 甲方 SDK，提供 OSC_POSE 控制器 |

### 不需要
- ❌ `pygame` / `vgamepad` / `hidapi` — 手柄是纯 `ctypes` 实现的 XInput
- ❌ LeRobot / h5py — 那是数据采集模块，与本模块无关

详细见 `requirements.txt`。

---

## 五、能否在其他电脑上运行？

**简短回答：代码本身可以，但需要配套环境。**

本文件夹已做到**完全自包含**（零外部绝对路径），拷到别的机器不会因为路径问题失败。
但仍依赖两台机器之外的三个条件：

| 条件 | 是否随文件夹走 | 说明 |
|---|---|---|
| Python + numpy/scipy | ❌ | 需在新机器安装 |
| `orca_gym`（含 mujoco） | ❌ | 需装甲方 SDK，版本要与仿真端一致 |
| **OrcaLab 仿真端在跑** | ❌ | 本模块是**客户端**，必须有仿真服务 |
| 手柄硬件 | ❌ | 用键盘模式可绕开 |
| 代码与标定表 | ✅ | 已全部在本文件夹内 |

### 逐项说明

**1. 代码与资源 — ✅ 可移植**
`gripper_table.json` 已收进 `assets/`，不再依赖原来那个 `2026-09-17\xai\work` 目录。

**2. Python 环境 — ❌ 需重建**
新机器要装 Python 3.11 + `numpy` + `scipy`。

**3. `orca_gym` — ❌ 最大的门槛**
这是甲方私有 SDK，且**版本必须与仿真端匹配**（甲方提过 7.x 与 8.x 的相机接口不兼容）。
建议直接复制整个 `orcalab` conda 环境，或按甲方文档重建。

**4. 仿真端 — ❌ 必须有**
`teleop.py` 是**客户端**，通过 gRPC 连 `localhost:50051`。
仿真没开就会报：

```
AioRpcError: ... 127.0.0.1:50051: Connection refused
```

**5. 键盘模式 — ✅ 无需手柄**
没有手柄的机器用 `--keyboard` 即可，这也是做键盘方案的原因。

**6. 操作系统 — ⚠️ 仅 Windows**
- `gamepad.py` 用 `xinput1_4.dll`
- `keypad.py` 用 `user32.GetAsyncKeyState`

两者都是 Windows API，**Linux/macOS 无法直接运行**（需改写输入层，运动控制部分可复用）。

### 移植步骤建议

```powershell
# 1. 拷整个 teleop/ 文件夹到新机器
# 2. 装环境（推荐直接复制 conda 环境）
conda create -n orcalab --clone orcalab
# 或按甲方文档安装 orca_gym

# 3. 启动 OrcaStudio 仿真端，确认 50051 在监听
# 4. 在新机器上跑通自检（不需要仿真）
python -X utf8 tests\test_keypad.py

# 5. 连接仿真跑主程序
python -X utf8 -u teleop.py --keyboard --flip-lr
```

---

## 六、测试

```powershell
cd teleop

# 键盘单元测试（无需仿真/手柄）
python -X utf8 tests\test_keypad.py

# 键盘真机语义自检
python -X utf8 tests\test_keypad_realtime.py

# 端到端联调（验证键盘能驱动 teleop 的运动逻辑）
python -X utf8 tests\test_teleop_keyboard_integration.py

# 摩擦参数实验（回答「抓取滑脱调什么」）
python -X utf8 tests\exp_friction_study.py
```

需要仿真端在跑：

```powershell
# 读取仿真实体的接触参数（friction / condim / solref / solimp）
python -X utf8 tests\diag_contact.py
```

---

## 七、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `Connection refused ... 50051` | 仿真端没开 | 启动 OrcaStudio |
| 按键盘无反应 | 忘了加 `--keyboard` | 加该参数 |
| 方向相反 | 相机位置 | 加/去掉 `--flip-lr` |
| 手柄不识别 | XInput 槽位 | `--index 1` 换槽位 |
| 某几个键同时按无效 | 键盘 ghosting | 减少同时按键 |

---

## 八、已知限制

1. **仅 Windows**（输入层用 Windows API）
2. **键盘是开关量**，不如手柄摇杆（模拟量）细腻，靠 SHIFT/CTRL 分档近似
3. **必须有仿真端**，本模块不能独立运行
4. `orca_gym` 版本须与仿真端一致

---

## 九、换一台电脑（环境已配好）能直接跑吗？

**能，但先确认两个场景相关的值。** 详见 `docs/移植性说明.md` 的补充章节。

### 代码是自适应的

`orca_rig.py` 按**名字**自动查找关节，不写死索引：

```python
cands = sorted(n for n in self.joints if f"arm_{side}_joint{k}" in n)
```

* 双臂 / 夹爪关节 —— 按名字前缀自动发现
* 场景物体（药盒/药瓶/托盘）—— 连接时自动快照

所以**布局不同也能跑**，只要机器人命名一致。

### 两处需要留意

| 项 | 默认值 | 说明 |
|---|---|---|
| `env_index` | 93 | 场景索引，可用 `--env-index` 覆盖 |
| `agent` | `dual_arm_collaborative_service_robot_1` | 机器人名，可用 `--agent` 覆盖 |

```powershell
python -X utf8 -u teleop.py --keyboard --flip-lr `
    --env-index 93 --agent dual_arm_collaborative_service_robot_1 `
    --addr localhost:50051
```

### 排查

| 报错 | 处理 |
|---|---|
| `missing arm_l_joint1` | 用 `--agent` 指定正确的机器人名 |
| `missing gripper_r ...` | 同上 |
| `Connection refused :50051` | 开仿真端，或用 `--addr` 指定 |
