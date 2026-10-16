# 采集用法（三相机 + LeRobot 直存）

环境：C:\Users\<你的用户名>\miniconda3\envs\orcalab281\python.exe
前置：OrcaStudio 26.9.1 已打开场景，仿真处于「外部控制」模式。

## 一条命令（推荐）

    cd <仓库目录>\scripts\collect
    & "<你的orcalab281环境>\python.exe" collect.py `
        --keyboard --cam3-ws `
        --lerobot-out D:\data\lerobot\pick_medbox --task "pick the medbox" `
        --lerobot-fps 20

按键：
    I = 开始/结束录制      K = 待命 / 取消 / 中止
    J = 保存               L = 丢弃
    N = 全场景复位（物体 + 双臂 + 夹爪回起点）
    其余遥操作键（X 换臂 / A 闭爪 / B 开爪 / 摇杆）不变

## 产物（标准 LeRobot v3.0，可直接训练）

    <lerobot-out>/
      data/chunk-000/file-000.parquet        observation.state(44) + action(8)
      videos/observation.images.head/...     camera_head  640x480 mp4
      videos/observation.images.left/...     camera_left  640x480 mp4
      videos/observation.images.right/...    camera_right 640x480 mp4
      meta/info.json  stats.json  tasks.parquet  episodes/

读回来验证：

    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds = LeRobotDataset(repo_id="local/x", root=r"D:\data\lerobot\pick_medbox",
                        video_backend="pyav")     # Windows 必须加 video_backend="pyav"
    print(len(ds), ds[0]["observation.images.head"].shape)

## 相机来源（重要）

采集**只应该**用机器人自带的相机。三台相机都挂在机器人身上（可用
`python check_camera_source.py` 随时核验）：

    camera_head   -> .../head_link2/.../camera_head            端口 7070
    camera_left   -> .../arm_l_end_link/.../camera_left        端口 7080
    camera_right  -> .../arm_r_end_link/.../camera_right       端口 7090

    --cam3-ws            ★ 机器人自带三相机 · WebSocket 推流（30Hz, 640x480）。**默认**
    --cam3               机器人自带三相机 · Studio 视口渲染（~0.6fps，慢）
    --camera             ✗ Studio 离屏 AgentCamera（**悬浮相机**，不属于机器人）
                         默认已被拒绝；确实要用请加 --allow-floating-camera
    --no-camera          不接任何相机（纯 state/action 采集）

> 不加任何相机开关时，现在**默认走 `--cam3-ws`**（机器人自带三相机）。
> 以前不加开关是"不接相机"，加了 `--camera` 会采到悬浮相机 —— 这两点都已改掉。

## 常用开关

    --lerobot-out DIR      存 LeRobot（推荐）
    --lerobot-resume       追加到已有数据集（第二场接着写）
    --lerobot-no-videos    用 parquet 内嵌 PNG 而不是 mp4
    --no-lerobot           退回老 HDF5 格式（存到 --dataset）
    --lerobot-fps N        写进 meta 的帧率

## 自测脚本

    python check_camera_source.py         # ★ 核验相机来源：是否机载 / 有无悬浮相机 / 端口
    python ws_camera.py --steps 90        # 只测三相机出图，存 out_final\ws_*.png
    python e2e_test.py --out <目录> --frames 120   # 免键盘跑完整链路

## 已知约束

* 仿真必须是「外部控制」，且渲染时 simulate_index 必须严格递增，
  否则引擎判定同帧、只推 1 帧（collect.py 的 _drive_sim 已处理）。
* Windows 下 LeRobot 必须 parallel_encoding=False（已内置）。
* 读视频要 video_backend="pyav"（torchcodec 在 Windows 上缺 FFmpeg DLL）。
* 三路 WebSocket 是**串行**连接，每路约 2s，启动时等约 7s 是正常的。
* ⚠️ **头部相机画面异常（未闭环）**：`camera_head` 因父节点 `scale` 未正确乘入相机偏移，
  取到的画面落在机器人头部外壳内壁；左右腕两台正常（与编辑器视口一致）。
  根因与修复方案见 [`相机取图根因结论与修复方案.md`](相机取图根因结论与修复方案.md)。
  **修复前，`observation.images.head` 这一路视频不可用**，训练时应先排除。
