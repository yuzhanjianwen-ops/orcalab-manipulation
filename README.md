# OrcaLab 双臂机器人操作与数据采集

> 基于 OrcaLab / OrcaGym 的双臂协作机器人**遥操作**与**数据采集**工程。
> 手柄与键盘两套控制方案并行，互不影响。

---

## 1. 这是什么

本工程解决两件事：

| 能力 | 说明 | 入口 |
|---|---|---|
| **遥操作** | 用手柄（XInput）或键盘实时控制双臂协作机器人（OSC_POSE 末端控制 + 夹爪） | `scripts/teleop/teleop.py` |
| **数据采集** | 在遥操作过程中录制 episode，按键打标，落盘为 HDF5 数据集 | `scripts/collect/collect.py` |

两者可独立运行，也可组合运行（`collect.py` 内部会调用 `teleop` 的控制模块）。

---

## 2. 目录结构

```
orcalab-manipulation/
├── README.md                     本文件（项目总说明）
├── requirements.txt              运行依赖汇总
├── scripts/                      所有可执行代码
│   ├── teleop/                   遥操作（手柄 + 键盘）
│   │   ├── teleop.py             ★ 遥操作主程序（手柄/键盘统一入口）
│   │   ├── gamepad.py            XInput 手柄读取（纯 ctypes，无第三方库）
│   │   ├── keypad.py             键盘读取（Windows 异步键盘钩子）
│   │   ├── orca_rig.py           机器人刚体/关节封装，与 OrcaGym 通信
│   │   ├── osc_arm.py            OSC_POSE 控制器封装（源自甲方 OrcaManipulation）
│   │   ├── teleop_view.py        视角方向映射（flip-lr / flip-fb）
│   │   ├── assets/gripper_table.json  夹爪标定表
│   │   ├── requirements.txt      遥操作依赖
│   │   └── README.md             遥操作子模块说明
│   └── collect/                  数据采集
│       ├── collect.py            ★ 采集主程序（遥操作 + 录制 一体）
│       ├── recorder.py           采集状态机与 episode 内存缓冲
│       ├── keymap.py             手柄十字键 / 键盘 → 状态机 映射
│       ├── fields.py             每帧采集字段（从 OrcaRig 抓取）
│       ├── saver_hdf5.py         HDF5 落盘（默认）
│       ├── collect_lerobot.py    ★ 采集主程序（LeRobot v3.0 落盘）
│       ├── saver_lerobot.py      LeRobot v3.0 落盘（parquet + 视频）
│       ├── orca_boot.py          沙箱引导模块（必须在 import orca_gym 之前导入）
│       ├── orca_mcp.py           MCP 客户端（创建/查询 env 等）
│       ├── camera_verify.py      相机连通性自检
│       ├── robot_cam_enable.py   机器人自带相机尝试启用
│       ├── official_camera.py    引擎相机取图封装
│       ├── ws_camera.py          WebSocket 相机推流封装
│       ├── view_camera.py        视口相机取图
│       ├── camera_doctor.py      相机诊断
│       └── _fov_probe/           相机排查探针脚本归档
├── data/                         采集产出
│   └── dataset/<时间戳>_<短uuid>/
│       ├── episode.hdf5          每帧数据
│       └── meta.json             episode 元信息
├── docs/                         全部文档（见第 6 节）
├── scenes/                       场景 JSON 与资产路径维护脚本（见 scenes/README.md）
│   ├── SimpleMovement2.json      ★ 主场景
│   ├── SimpleMovement2_robot_cam.json  同上，但机器人换成「带相机」prefab
│   ├── camera10_11.json          相机标定场景（三台机载相机定义）
│   ├── fix_scene_asset_paths.py  修正场景里失效的资产路径
│   └── ...
├── environment.yml               完整 conda 环境（orcalab281，170 包，精确复现用）
├── requirements-lock.txt         同上，pip 视角的锁定清单
├── tests/                        测试与验证脚本
├── materials/                    交付辅助材料（截图 / 录像 / 说明）
└── 3rd-party/                    第三方 / 甲方代码（只读参考，**未纳入本仓库**，见第 9 节）
    ├── OrcaManipulation/         甲方官方仓库副本（OSC 控制器、数采格式来源）
    ├── OrcaGym/                  OrcaGym 参考副本
    └── lerobot/                  huggingface/lerobot（LeRobot v3.0 格式来源）
```

### 仓库里有什么 / 没什么

本仓库只版本化**源码、配置与文档**，克隆下来约 **2 MB**。以下内容被 `.gitignore` 排除：

| 排除项 | 体积 | 原因 |
|---|---|---|
| `3rd-party/` | ~414 MB | 上游仓库（lerobot / OrcaManipulation / OrcaGym），各有独立仓库 |
| `/assets/` | ~330 MB | 机器人 prefab 二进制网格与贴图（见下方说明，**由云端资产库提供**） |
| `scripts/collect/dataset/`、`data/` | ~240 MB | 采集产出（`episode.hdf5` 单文件 236MB，超 GitHub 100MB 限制） |
| `scripts/collect/` 下调试截图、根目录 `*.png` | ~230 MB | 相机排查过程中的对比图，属过程产物 |
| `_cam_test*/` `_diag/` `_now/` `_show/` `backup/` | ~32 MB | 临时目录与备份 |

> **关于资产**：场景 JSON 里出现的 `assets/e071469a36d3c8aa/...` 是 OrcaLab **云资产库的
> 虚拟路径**，不对应仓库内的真实目录。这些资产以 `.pak` 包形式由 OrcaStudio 按需下发
> （`user/downloaded_packages/`），场景打开时依据 `package_references` 字段自动同步 ——
> **不需要随仓库分发**。前提是运行机已登录 OrcaLab 账号且订阅了对应资产包，
> 清单见 `scenes/README.md`。
>
> 需要完整可运行环境时，只需补齐 `3rd-party/`（各上游仓库地址见第 9 节）。

### 环境复现

| 文件 | 用途 |
|---|---|
| `environment.yml` | **完整 conda 环境**（`orcalab281`，Python 3.12.13 + 170 个包），一键重建 |
| `requirements-lock.txt` | 同上，`pip freeze` 视角的精确版本锁定 |
| `requirements.txt` | 仅顶层依赖摘要，供人工阅读 |

```powershell
# 精确重建（推荐）
conda env create -f environment.yml
# 或在已有环境里补齐
& "<你的python.exe>" -m pip install -r requirements-lock.txt
```

---

## 3. 环境要求

| 项 | 值 |
|---|---|
| 操作系统 | Windows 10 / 11 |
| Python | `<你的orcalab环境>\python.exe`（我们用的是 conda env `orcalab281`，见 `environment.yml`） |
| 关键点 | **必须加 `-X utf8`**（代码与日志含中文，缺了会 UnicodeEncodeError） |
| 仿真端 | OrcaStudio / OrcaLab 需先启动并加载好场景 |
| Python 版本 | 3.12（OrcaGym 环境自带） |

依赖见 `requirements.txt`。其中 `numpy` / `scipy` 需自行安装，`mujoco` / `gymnasium` / `orca_gym` 由 OrcaLab 环境提供，**不要单独 pip 安装**。

---

## 4. 快速开始

### 4.1 遥操作（手柄）

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\scripts\teleop
& "<你的orcalab环境>\python.exe" -X utf8 -u teleop.py --flip-lr
```

### 4.2 遥操作（键盘）

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\scripts\teleop
& "<你的orcalab环境>\python.exe" -X utf8 -u teleop.py --keyboard --flip-lr
```

### 4.3 采集（键盘，推荐先试）

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\scripts\collect
& "<你的orcalab环境>\python.exe" -X utf8 -u collect.py --keyboard --flip-lr
```

### 4.4 采集（手柄）

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\scripts\collect
& "<你的orcalab环境>\python.exe" -X utf8 -u collect.py --flip-lr
```

> `--flip-lr` ：**相机在机器人背后**时必须加（你我现场就是这个配置）。
> 前后反了再加 `--flip-fb`。

### 4.5 采集（LeRobot v3.0 格式）

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\scripts\collect
& "<你的orcalab环境>\python.exe" -X utf8 -u collect_lerobot.py `
    --keyboard --flip-lr --lerobot-out D:/data/lerobot/pick_medbox
```

> **环境已配好**（lerobot 0.6.2 editable + huggingface_hub/datasets/draccus）。
> 详见 `docs/LeRobot3.0采集使用说明.md`。

---

## 5. 常用启动参数

| 参数 | 作用 |
|---|---|
| `--keyboard` | 使用键盘控制（不写则用手柄） |
| `--flip-lr` | 左右方向镜像（相机在机器人背后时必加） |
| `--flip-fb` | 前后方向镜像 |
| `--dataset <dir>` | 指定数据集输出目录 |
| `--reset-key <键>` | 指定复位键（键盘模式） |
| `--no-reset-in-rec` | 录制过程中禁止复位改变数据 |
| `--no-render` | 不开可视化窗口 |

---

## 6. 文档索引（`docs/`）

| 文档 | 内容 |
|---|---|
| `复现指南.md` | **甲方必读**：从零复现的完整步骤、前置条件、资产订阅、验收清单、无法覆盖的事项 |
| `项目文档_代码地图与核心逻辑.md` | **先看这篇**：整体架构、模块职责、调用链 |
| `手柄说明书.md` | 手柄各按键作用与手感说明 |
| `键盘操作使用说明书.md` | 键盘各按键作用与手感说明 |
| `键盘驱动说明.md` | 键盘钩子的实现原理与注意事项 |
| `手腕姿态方向问题分析与修复.md` | 手腕旋转方向 bug 的定位与修复记录 |
| `采集使用说明.md` | 采集流程、按键、数据格式、落盘位置 |
| `LeRobot3.0采集使用说明.md` | **LeRobot v3.0 采集**：安装、启动、按键、产出结构 |
| `甲方仓库_数采代码与格式分析.md` | 甲方官方仓库的数采代码 / 机器人 / 格式分析 |
| `相机接入排查结论.md` | 相机为什么用不了（含实测证据） |
| `相机资产接入实操.md` | 相机资产在 Studio 里的拖放/挂载步骤 |
| `移植性说明.md` | 换一台电脑要改哪些东西 |
| `PRESET.md` | 预设参数与推荐组合 |
| `README.md` | 文档目录本身的说明 |

---

## 7. 数据格式

支持**两种格式**，按需选用：

| 脚本 | 格式 | 说明 |
|---|---|---|
| `collect.py` | **HDF5** | 自研，每集一个目录 |
| `collect_lerobot.py` | **LeRobot v3.0** | 标准数据集，可直接用于 lerobot 训练 |

### HDF5 格式

每条 episode 一个目录：

```
data/dataset/<YYYY-MM-DD_HHMMSS>_<短uuid>/
├── episode.hdf5
└── meta.json
```

每帧字段见 `docs/采集使用说明.md`（joint_pos / joint_vel / gripper_pos / ee_pos / ee_quat / action_* / timestamp 等）。

**图像**：字段 `image` 已预留，但**当前为空** —— 场景内 MuJoCo `<camera>` 数量为 0，相机推流未打通，需甲方在 OrcaStudio 侧配置。**没有相机也能正常采集**，只是 episode 里没有图像。

---

## 8. 新机器上跑起来（移植要点）

> 完整的分步复现流程见 **`docs/复现指南.md`**（含前置条件、资产同步、验收步骤）。
> 下面是最小要点。

1. 装好 OrcaLab / OrcaStudio **26.8.1** 与 `orcalab281` conda 环境（版本需与仿真端一致；
   环境清单见 `environment.yml`）。
2. 启动 OrcaStudio，加载 `scenes/SimpleMovement2.json`（**主场景**）。
3. 本目录可整份拷走，**无需改动代码**（路径均为相对当前文件的 `HERE` 推导）。
4. 若目录结构被打乱，可用环境变量兜底：
   ```powershell
   $env:ORCA_TELEOP_DIR = "<你的路径>\scripts\teleop"
   ```

---

## 9. 第三方代码（`3rd-party/`）

本目录存放**外部来源代码**，只读参考，不属于我们的交付代码。

| 目录 | 来源 |
|---|---|
| `3rd-party/OrcaManipulation/` | [openverse-orca/OrcaManipulation](https://github.com/openverse-orca/OrcaManipulation) |

### 我们参考了它的什么

| 我们的模块 | 甲方对应内容 |
|---|---|
| `scripts/teleop/osc_arm.py` | `src/controllers/` 的 **OSC_POSE** 控制器 |
| `scripts/collect/fields.py`、`saver_hdf5.py` | `src/dataStorage/G1OmniPickerDataStorage` 的 HDF5 字段设计 |
| `scripts/collect/`（整体流程） | `SCRIPT-BASED-COLLECTION.md`、`src/envs/dataCollection/` |

> `3rd-party/` 本身**未纳入本仓库**（体积 414 MB，且 lerobot 自带 `.git`）。
> 各上游来源与获取方式见上表；如需完整参考，按上表地址自行克隆即可。
> 若交付时不需要带第三方源码，**删掉整个 `3rd-party/` 即可**，不影响运行 ——
> 我们的代码只依赖 `orca_gym`（由 OrcaStudio 提供）与 `lerobot`（pip 安装），
> 均**不依赖** `3rd-party/` 里的副本。

---

## 10. 已知限制

| 项 | 状态 |
|---|---|
| 相机图像字段 | ❌ 未打通（待甲方 Studio 侧配置相机并推流） |
| LeRobot 3.0 采集 | ✅ **已完成并验证**（collect_lerobot.py）；环境已配（lerobot 0.6.2），实采 243 帧通过 |
| 遥操作手感 | ✅ 方向已校准（`--flip-lr` 组合已验证五个方向全对） |

---

## 11. 常见问题

**Q：`can't open file 'teleop.py'`？**
A：路径写错了。先 `cd` 到 `scripts\teleop`，或用完整路径调用。

**Q：按键盘没反应？**
A：确认加了 `--keyboard`；键盘方案与手柄方案互不冲突，但同一次运行只能选一种。

**Q：抓取时穿模？**
A：调整资产的接触参数（`solref` / `solimp` / `condim` / `friction`），与代码无关。

---

_整理日期：2026-10-01_
