# OrcaLab 双臂遥操作数据采集（进行中）

- **创建日期**：2026-09-25
- **目标格式**：HDF5（先用；LeRobot 3.0 待甲方确认后写转换脚本）
- **当前状态**：**已打通，可实际采集** ✅（2026-09-28）

---

## 一句话现状

**采集链路已打通，可以实际采数据了。** `collect.py` 把状态机、按键、字段、落盘
接到遥操作主循环上，实测 ~19.5 fps 稳定运行，落盘字段全部正确。

只剩一件事：**相机**。实测发现场景里 MuJoCo `<camera>` 数量为 **0**，
只有 3 个相机占位 body（详见 `相机接入排查结论.md`）——
相机是 OrcaStudio 侧的配置，**客户端无法创建**，需要甲方在 Studio 里配好。
**没有相机也能正常采集**，只是 episode 里没有 `image` 字段。

---

## 目录结构

```
2026-09-23-datacollect/
├── README.md              本文件
├── orca_boot.py           ★ 沙箱引导模块（必须在 import orca_gym 之前导入）
├── recorder.py            ★ 采集状态机 + episode 内存缓冲
├── keymap.py              ★ 十字键 -> 状态机 映射（含边沿检测）
├── fields.py              ★ 每帧字段采集（从 OrcaRig 抓数据）
├── saver_hdf5.py          HDF5 落盘（参考甲方）
├── collect.py             ★ 总装脚本 —— 采集主程序
├── 采集使用说明.md         ★ 使用文档（启动/按键/格式/排错）
├── 相机接入排查结论.md      相机为什么没有（实测证据）
├── probes/                排查脚本归档
├── demo_offline.py        离线端到端演练（不连仿真）
├── test_recorder.py       状态机测试（27 项）
├── test_keymap.py         按键映射测试（11 项）
├── test_saver.py          落盘测试（14 项）
└── run_all_tests.py       一键跑全部测试
```

---

## 按键方案（操作者已确认）

| 按键 | 功能 | 说明 |
|---|---|---|
| **十字下** | 进入待命 / 取消 / 中止 | 两段式防误触的第一段 |
| **十字上** | 开始 / 结束录制 | 复用，按一下开始、再按一下结束 |
| **十字左** | 保存 | 只在 REVIEW 状态有效 |
| **十字右** | 丢弃 | 只在 REVIEW 状态有效 |

**设计要点**：不占用 A / B（夹爪）、X（切换手臂）、Y（回工作位）、START、BACK，
**原有遥操作手感完全不受影响**。

**复位键**：原版 `teleop.py` 用「十字下」做全场景重启，采集时该键被状态机占用，
复位改绑到 **手柄 RSTICK / 键盘 N**。**录制过程中也可以复位**，数据会继续记录，
并在每帧写入 `n_resets` 字段（`--no-reset-in-rec` 可关闭）。

**数据位置**：每条 episode 一个目录，名字带采集时间
（`2026-09-28_164713_96b72dde/`）。位置另记录在 `DATASET_LOCATION.txt`。

### 状态机

```
IDLE ──[十字下]──> READY ──[十字上]──> RECORDING ──[十字上]──> REVIEW
  ^                  │                                          │
  │              [十字下]=取消                              [十字左]=保存
  │                  │                                    [十字右]=丢弃
  └──────────────────┴──────────────────────────────────────────┘
                     RECORDING 中按[十字下] = 安全中止并丢弃
```

### 安全设计

- `IDLE` 状态下十字上 / 左 / 右**全部无效**，防止误触
- `READY` 状态下再按十字下 = **取消待命**
- `RECORDING` 中按十字下 = **强制中止并丢弃**
- 只有 `REVIEW` 状态"保存"才真正落盘，其余数据留在内存

---

## 采集字段

参考甲方 `G1OmniPickerDataStorage` 的 HDF5 设计，做了裁剪适配：

| 字段 | 形状 | 含义 |
|---|---|---|
| `timestamp` | 标量 | 相对录制开始的秒数 |
| `joint_pos` | (14,) | 双臂 7+7 关节角 |
| `joint_vel` | (14,) | 双臂 7+7 关节角速度 |
| `gripper_pos` | (16,) | 双夹爪 8+8 关节角 |
| `ee_pos` | (6,) | 双臂末端位置 xyz |
| `ee_quat` | (8,) | 双臂末端姿态四元数 xyzw |
| `active_arm` | 标量 | 0=左臂 1=右臂 |
| `action_pos` | (3,) | 活动臂末端目标位置 |
| `action_quat` | (4,) | 活动臂末端目标姿态 xyzw |
| `action_rot6d` | (6,) | 目标姿态 6D 表示（可选） |
| `action_gripper` | 标量 | 夹爪开合指令 |
| `image` | (H,W,3) | 相机图像 uint8（**相机就绪后自动填充**） |

**相对甲方去掉的字段**：底盘 `front_drive`（本任务用不到）、`body_slide`（本机器人无此关节）。

---

## 与相机解耦的设计

`recorder.py` **不直接依赖相机**，通过依赖注入接入：

```python
rec = Recorder()
rec.set_image_fn(lambda: camera.image)   # 相机就绪后注入
rec.set_saver(hdf5_saver)                # 格式确定后注入
```

好处：
1. 相机没通时**照常采集状态数据**，不阻塞
2. 格式没定时**数据留在内存**，不丢现场
3. 加相机 / 换格式都**不用改核心逻辑**

---

## 沙箱说明（重要）

本机跑 AI 沙箱时，`orca_gym` 的日志会写往
`<site-packages>/logs/orca_gym.log`，而该文件对沙箱账号只读，
导致 `import orca_gym` 直接 `PermissionError` 崩溃。

**解法**：`orca_boot.py` 在 import `orca_gym` 之前劫持 `RotatingFileHandler`，
把日志重定向到可写目录。

**用法（必须最先导入）**：

```python
import orca_boot          # noqa: F401  <- 必须在最前面
from orca_gym.sensor.rgbd_camera import CameraWrapper
```

**该模块不修改 site-packages 内任何文件**，也不影响正常用户
（正常用户直接 `import orca_gym` 不受影响）。

---

## 依赖状态

| 包 | 状态 | 用途 |
|---|---|---|
| `h5py` | ✅ 已装 3.16.0 | HDF5 落盘 |
| `av` | ✅ 已装 18.1.0 | 解码相机 H.264 流 |
| `opencv-python` | ✅ 已装 5.0.0 | 图像格式转换 |
| `websockets` | ✅ 已装 17.0.1 | 连接相机推流 |
| `lerobot` | ❌ **未装** | LeRobot 3.0 格式（待确认是否需要） |

---

## 启动采集

```powershell
# 1. 先打开 OrcaStudio，加载好场景
# 2. 再运行：
cd <项目目录>
& "<你的orcalab环境>\python.exe" -X utf8 -u collect.py --flip-lr
```

详细说明见 **`采集使用说明.md`**。

---

## 待办

### 已完成 ✅

- ~~主采集脚本 `collect.py`~~ — 已实现并端到端验证
- ~~落盘格式~~ — 先用 HDF5 跑通（甲方也在用 HDF5）

### 阻塞项

1. **相机** — 场景里 `<camera>` 数量 = 0，只有占位 body。
   需要甲方在 OrcaStudio 里**创建相机**并配置 RGB 端口（7070）。
   客户端只能"激活已存在的相机"，不能创建。
   配好后加 `--camera 7070` 即可，代码不用改。

### 待接入

2. LeRobot 3.0 转换脚本（等甲方确认格式要求；HDF5 作为中间格式更好转）

---

## 测试

```powershell
cd <项目目录>
& "<你的orcalab环境>\python.exe" -X utf8 run_all_tests.py
```

当前结果：**52 passed, 0 failed**

| 测试文件 | 项数 | 覆盖内容 |
|---|---|---|
| `test_recorder.py` | 27 | 状态转移、误触防护、堆叠、图像注入、落盘钩子 |
| `test_keymap.py` | 11 | 边沿检测、长按不连发、四方向不串扰 |
| `test_saver.py` | 14 | HDF5 往返读写、字段形状、属性、meta.json |
