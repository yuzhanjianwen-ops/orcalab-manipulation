# OrcaStudio 场景文件（`scenes/`）

> 本目录是从 OrcaStudio 工程目录 `D:\OTHERS\OrcaLab\SimpleMovement\`
> 摘出来的场景布局与其维护脚本，随本仓库一起版本化，**不是** OrcaStudio 的运行目录。
> 实际使用时请把文件放回 OrcaStudio 的场景目录（或直接用 `layouts/` 里的副本）。

## 一、场景 JSON

| 文件 | 说明 |
|---|---|
| `SimpleMovement2.json` | **主场景**（双臂机器人 + 桌面 + 药品，当前使用） |
| `SimpleMovement3.json` | 备选场景 |
| `SimpleMovementCamera.json` | 带相机的场景变体 |
| `camera10_11.json` | 相机标定场景：三台机载相机 `camera_head` / `camera_left` / `camera_right` 的完整定义（含 `/dual_arm_collaborative_service_robot_1` 的 `scale = 1.695356845855713`） |
| `camera_3.json` | 早期三相机场景 |
| `camera.json` | 早期单相机场景 |
| `SimpleMovement.json` | 初版基础场景 |

## 二、维护脚本

| 脚本 | 作用 |
|---|---|
| `fix_scene_asset_paths.py` | **批量修正场景里失效的资产路径**。用于解决打开布局时报「跳过 /wooden_lattice_tray_1，资产 …/basket_wood 不存在」这类错误（把已改名的资产 ID 映射回现存的包）。默认 dry-run，确认后加参数实际写入并自动备份。 |
| `fix_scene_package_ids.py` | 批量修正场景里的资产包 ID（package id）。 |
| `_pkg_check.py` | 检查场景引用的资产包是否都能在本地资产库中找到（巡检用）。 |

## 三、用法

```powershell
# 1) 先巡检：列出场景里引用了但本地不存在的资产
& "<orcalab 环境>\python.exe" -X utf8 _pkg_check.py

# 2) 修资产路径（先跑 dry-run 看会改哪些，再实际写入）
& "<orcalab 环境>\python.exe" -X utf8 fix_scene_asset_paths.py --dry-run
& "<orcalab 环境>\python.exe" -X utf8 fix_scene_asset_paths.py --apply
```

> 两个 `fix_*` 脚本在写入前都会自动生成 `*.bak_<时间戳>` 备份，
> 回滚直接把备份改回原名即可。

## 四、注意

- `*.json.bak_*`、`*.json.mycamera_change_*` 等历史备份**未**纳入本仓库。
- 场景文件里的资产路径与包 ID 会随资产库变动，跨机器使用时先跑一遍
  `_pkg_check.py` 再跑 `fix_scene_asset_paths.py`。
