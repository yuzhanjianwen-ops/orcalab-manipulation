# LeRobot v3.0 数据采集使用说明

> 在原有采集链路上增加 **LeRobot v3.0 格式落盘**，参考甲方
> `OrcaManipulation/src/dataStorage/lerobot_data_storage.py` 实现。
>
> **状态：已于 2026-10-04 完成环境配置 + 真实采集验证（243 帧）**
> 文档更新日期：2026-10-04

---

## 一、新增了什么

| 文件 | 作用 |
|---|---|
| `scripts/collect/saver_lerobot.py` | LeRobot v3.0 落盘器（`Recorder.set_saver` 注入点） |
| `scripts/collect/collect_lerobot.py` | 采集主程序（遥操作 + 状态机 + **LeRobot 落盘**） |
| `tests/test_saver_lerobot.py` | 离线单测（14 项） |

**原有文件全部未改动**（`collect.py` 仅保留此前的路径适配），
HDF5 采集与 LeRobot 采集**两套并存，互不影响**。

---

## 二、和 collect.py 的关系

```
        ┌───────────────────────────────────────┐
        │  共用的部分（完全一样）                │
        │  遥操作 / 状态机 / 按键 / 相机 / 复位  │
        └───────────────┬───────────────────────┘
                        │
        ┌───────────────┴────────────────┐
        ▼                                ▼
   collect.py                    collect_lerobot.py
   Hdf5Saver                     LeRobotSaver
   → data/dataset/...            → lerobot_out/...
```

`collect_lerobot.py` 继承自 `collect.py` 的 `CollectTeleop`，
**只替换落盘器一个环节**，所以手感、按键、相机行为**完全一致**。

---

## 三、环境配置（已于 2026-10-04 完成）

### 3.1 实际环境

| 项 | 值 |
|---|---|
| 环境 | `orcalab`（`C:\Users\86322\.conda\envs\orcalab`） |
| Python | 3.12.13 |
| lerobot | **0.6.2**（**editable 安装**，指向 `3rd-party/lerobot`） |

### 3.2 安装步骤（复现用）

```powershell
$py = "C:\Users\86322\.conda\envs\orcalab\python.exe"

# 1) 补三个缺失依赖
& $py -m pip install huggingface_hub datasets draccus

# 2) 装本地 lerobot 0.6.2（--no-deps 防止 pip 去动已合规的 torch/opencv）
& $py -m pip install -e "D:\OTHERS\projects\orcalab-manipulation\3rd-party\lerobot" --no-deps
```

> **为什么用 `--no-deps`**：lerobot 的 `pyproject.toml` 挂着 `torchcodec`、
> `lancedb`、`rerun-sdk` 等一堆可选依赖，带依赖装会拽进不必要的东西，
> 甚至可能降级已有的 opencv/torch。

### 3.3 依赖现状（都已满足，无需再装）

| 包 | 版本 | lerobot 0.6.2 要求 | 状态 |
|---|---|---|---|
| python | 3.12.13 | `>=3.12` | ✅ |
| torch | 2.11.0+cu128 | `>=2.7,<2.12` | ✅（CUDA 可用） |
| torchvision | 0.26.0+cu128 | `>=0.22,<0.27` | ✅ |
| numpy | 2.2.6 | `>=2.0,<2.3` | ✅ |
| av | 15.1.0 | `>=15.0,<16` | ✅ |
| pyarrow | 25.0.1 | `>=14` | ✅ |
| pandas | 2.3.3 | — | ✅ |
| einops / tqdm / safetensors | 0.8.2 / 4.70.1 / 0.8.0 | — | ✅ |
| huggingface_hub | 1.33.0 | — | ✅ 本次新增 |
| datasets | 4.8.5 | — | ✅ 本次新增 |
| draccus | 0.11.6 | — | ✅ 本次新增 |

### 3.4 环境备份与回滚

配置前的完整快照在：

```
backup/env-20261004/
├── rollback.ps1                    ← 一键回滚
├── requirements-pip-freeze.txt     ← 159 个包精确版本
├── conda-list.txt                  ← conda 层 177 个包
├── site-packages-dirs.txt          ← 330 个目录快照
├── wheels/                         ← 三个依赖的离线 wheel
└── pip-list*.txt / env-info.txt / dist-info.txt
```

回滚命令：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\OTHERS\projects\orcalab-manipulation\backup\env-20261004\rollback.ps1"
```

### 3.5 已知问题：torchcodec 加载失败（无害）

启动时可能看到一大段 `libtorchcodec_core*.dll` 加载失败的堆栈，最后一句是：

```
'torchcodec' is installed but cannot be loaded ... Falling back to 'pyav' as a default decoder.
```

- **原因**：缺 full-shared 版 FFmpeg，DLL 依赖找不到
- **影响**：**仅视频读取解码**；lerobot 已自动回退 `pyav`
- **对纯状态采集的影响**：**零**（根本不碰解码器）
- **何时需要修**：接相机做视频**读取/校验**时

---

## 四、启动命令

### 4.1 键盘（推荐先试）

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\scripts\collect
& "C:\Users\86322\.conda\envs\orcalab\python.exe" -X utf8 -u collect_lerobot.py `
    --keyboard --flip-lr `
    --lerobot-out D:\data\lerobot\pick_medbox
```

### 4.2 手柄

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\scripts\collect
& "C:\Users\86322\.conda\envs\orcalab\python.exe" -X utf8 -u collect_lerobot.py `
    --flip-lr `
    --lerobot-out D:\data\lerobot\pick_medbox
```

### 4.3 断点续采（追加到已有数据集）

```powershell
& "C:\Users\86322\.conda\envs\orcalab\python.exe" -X utf8 -u collect_lerobot.py `
    --keyboard --flip-lr `
    --lerobot-out D:\data\lerobot\pick_medbox --resume
```

### 4.4 ⚠️ 必须正常退出（Ctrl-C）

**parquet footer 只在退出时写入。** 如果直接关窗口 / 强杀进程，
数据集会缺 `meta/episodes/` 和 parquet footer，**读不出来**。

正常退出会看到：

```
[中断] 收到 Ctrl+C，正在收尾...
[LeRobot] 本次共保存 1 条 episode
[LeRobot] 数据集目录：D:\data\lerobot\pick_medbox
```

---

## 五、按键（与 collect.py 完全一致）

| 按键 | 手柄 | 键盘 | 作用 |
|---|---|---|---|
| 待命/取消/中止 | 十字下 | **K** | 进入待命；再按取消；录制中按则中止丢弃 |
| 开始/结束录制 | 十字上 | **I** | 按一下开始，再按一下结束 |
| 保存 | 十字左 | **J** | 只在待判定状态有效 |
| 丢弃 | 十字右 | **L** | 只在待判定状态有效 |
| 复位 | RSTICK | **N** | 全场景复位 |
| 夹爪开合 | A / B | — | 录制时记得操作，否则夹爪数据恒定 |

状态机：`IDLE → READY → REC → REVIEW`
只有 `REVIEW` 状态下「保存」才真正落盘。

---

## 六、产出结构（**v3.0 实际结构**）

```
<--lerobot-out 指定的目录>/
├── data/
│   └── chunk-000/
│       └── file-000.parquet          ← observation.state / action / timestamp
├── videos/                            ← 有相机时才有
│   └── observation.images.<cam>/
│       └── chunk-000/*.mp4
└── meta/
    ├── info.json                      ← fps / robot_type / features / codebase_version
    ├── stats.json
    ├── tasks.parquet                  ← ⚠️ 不是 tasks.jsonl
    └── episodes/
        └── chunk-000/
            └── file-000.parquet       ← ⚠️ 不是 episodes.jsonl
```

> **注意**：`episodes.jsonl` / `tasks.jsonl` 是 **v2.x 旧格式**
> （lerobot 内部叫 `LEGACY_*`）。v3.0 全部改成了 parquet，
> 并且 `episodes` 是一个**带 chunk 分层的目录**。

### 字段映射

| LeRobot feature | 来源（我们每帧的字段） | 维度 |
|---|---|---|
| `observation.state` | `joint_pos(14) + gripper_pos(16) + ee_pos(6) + ee_quat(8)` | **44** |
| `action` | `action_pos(3) + action_quat(4) + action_gripper(1)` | **8** |
| `observation.images.<cam>` | 相机 RGB（相机就绪后） | (3,H,W) |

> **夹爪维度说明**：`gripper_pos` 是 `GORDER`（每侧 8 关节）× 2 侧 = 16，
> 与 `STATE_NAMES` 一致（`orca_rig.py` 的 `gorder` 定义：inner_joint1~4 + outer_joint1~4）。

### 落盘时机（重要）

| 内容 | 何时写入磁盘 |
|---|---|
| `data/*.parquet` 数据 | 每集 `save_episode()` 后 |
| `meta/episodes/*.parquet` | **每集后立即**（`metadata_buffer_size=1`） |
| parquet footer | **只在 `close()` / `finalize()` 时**（即退出时） |

---

## 七、与甲方实现的对照

| 项 | 甲方 | 我们 |
|---|---|---|
| 写入时机 | **边采边写**（`SingleFrameTask` 流式 `add_frame`） | **按键判定后整条写**（`Recorder.save()` 时） |
| API | `LeRobotDataset.create/add_frame/save_episode` | **同上**（保证格式一致） |
| 视频编码 | LeRobot 内部 ffmpeg（`streaming_encoding=True`） | LeRobot 内部 ffmpeg |
| 多相机 | `SingleFrameTask` + future 严格对齐 sim_idx | 待相机就绪后接入 |
| 机器人 | OpenLoong / Tiangong2 | `dual_arm_collaborative_service_robot_1` |
| 时间戳 | LeRobot 自动 `frame_index / fps` | **同上** |
| parquet footer | 每集后 close writer 写 footer | 退出时 `finalize()` 统一写 |
| meta 落盘 | — | 每集立即（`metadata_buffer_size=1`） |

> 为什么我们不照搬"边采边写"：我们的状态机支持**丢弃**（十字右），
> 边写的话丢弃要回滚已写入的文件，成本高。先攒内存、判定后一次写入更稳。

---

## 八、目录与安全校验

`LeRobotSaver` 对输出目录的处理策略（**已修复，此前会报 FileExistsError**）：

| 情况 | 行为 |
|---|---|
| 拒绝危险 root | ❌ 当前目录 `.` / 用户 home / 空路径 |
| 非 resume + 目录**不存在** | ✅ 正常创建 |
| 非 resume + 目录**已存在且为空** | ✅ **自动清理空目录后创建**（上次失败的残骸） |
| 非 resume + 目录**已存在且非空** | ❌ **拒绝覆盖**，提示加 `--resume` 或换目录 |
| resume + 目录存在 | ✅ 追加 |

> **为什么拒绝非空目录**：`LeRobotDataset.create()` 内部是
> `mkdir(exist_ok=False)`，且非 resume 模式会清空 root。拒绝非空目录
> 是防止误删已有数据。

### 错误不再被掩盖

此前 `create()` 中途失败会留下**空目录**，导致**下一次**保存报
`FileExistsError`，把第一次的真实错误彻底掩盖。

现在：

- `create()` 失败 → **回滚残留空目录**
- 抛出带**完整 traceback** 的错误，绝不吞掉根因

---

## 九、测试

```powershell
cd D:\OTHERS\projects\orcalab-manipulation\tests
& "C:\Users\86322\.conda\envs\orcalab\python.exe" -X utf8 -u test_saver_lerobot.py
& "C:\Users\86322\.conda\envs\orcalab\python.exe" -X utf8 run_all_tests.py
```

当前：**66 passed, 0 failed**。

---

## 十、验证记录（2026-10-04 实测）

### 10.1 冒烟测试（离线）

用真机字段格式 + 真 `EpisodeBuffer.stacked()` 写入，再用 lerobot 读回：

```
info.json: codebase_version=v3.0  fps=20  robot_type=dual_arm_collaborative_service_robot_1
features:  observation.state float32 [44] / action float32 [8]
读回:      observation.state ((44,), torch.float32) / action ((8,), torch.float32)
```

### 10.2 真实采集（243 帧）

```
D:\data\lerobot\pick_medbox_2\
├── data/chunk-000/file-000.parquet                 57517 B
├── meta/info.json                                   3543 B
├── meta/stats.json                                 19063 B
├── meta/tasks.parquet                               2020 B
└── meta/episodes/chunk-000/file-000.parquet        38058 B
```

| 检查项 | 结果 |
|---|---|
| 帧数 | **243 帧**，与 info.json 一致 |
| timestamp | 0.0 → **12.1000**（= 242/20，精确）|
| `observation.state` | (44,) float32 ✅ |
| `action` | (8,) float32 ✅ |
| `task` | `'teleop'` ✅ |
| lerobot 读回 | ✅ **243 帧完整加载** |
| 运动数据 | ✅ 真实存在（`joint_pos_12` range=0.47，`ee_pos_4` range=0.32）|

**结论：产出为标准 LeRobot v3.0 数据集，可直接用于 lerobot 训练。**

---

## 十一、当前状态与限制

| 项 | 状态 |
|---|---|
| 脚本实现 | ✅ 完成 |
| 离线单测 | ✅ 14/14（全量 66/66） |
| 环境配置 | ✅ 完成（lerobot 0.6.2 + 3 依赖） |
| **实际跑通采集** | ✅ **已验证（243 帧）** |
| 图像字段 | ⏳ 相机未接入，暂为纯状态采集 |
| torchcodec | ⚠️ 加载失败（无害，已回退 pyav） |

### 下一步

1. **接入相机图像字段**（`observation.images.*`）
   - 相机走 gRPC `GetCameraFramePNG`（见 `相机资产接入实操.md`）
   - 需要在 `LeRobotSaver(cameras={...})` 填 `{名: {height, width}}`
   - 视频读取校验可能需要修 torchcodec/FFmpeg

---

_文档更新日期：2026-10-04_
