# OrcaStudio 场景文件（`scenes/`）

> 本目录是仓库内**唯一**的场景文件位置。文件摘取自 OrcaStudio 工程目录
> `D:\OTHERS\OrcaLab\SimpleMovement\`（以及早前的 `layouts/` 副本，
> 两者已于 2026-10-15 合并到此处，避免出现互相矛盾的重复版本）。
>
> 本目录**不是** OrcaStudio 的运行目录。实际使用时把 json 放回 OrcaStudio 的场景目录，
> 或在 Studio 里直接「打开场景」选这里的文件。

## 一、场景 JSON

| 文件 | 说明 |
|---|---|
| `SimpleMovement2.json` | ★ **主场景**（数据采集用）：双臂机器人 + 桌面 + 药物 + 三台静置相机 |
| `SimpleMovement2_robot_cam.json` | 与主场景相同，但机器人换成**带相机**的 prefab（`g1_omnipicker_with_camera_usda`） |
| `SimpleMovement3.json` | 备选场景 |
| `SimpleMovementCamera.json` | 带相机的场景变体 |
| `camera10_11.json` | 相机标定场景：三台机载相机 `camera_head` / `camera_left` / `camera_right` 的完整定义（含 `/dual_arm_collaborative_service_robot_1` 的 `scale = 1.695356845855713`） |
| `camera_3.json` | 早期三相机场景 |
| `camera.json` | 早期单相机场景 |
| `SimpleMovement.json` | 初版基础场景 |

每个场景 JSON 顶层的 `package_references` 字段记录了它依赖的**资产包**，
OrcaStudio 打开场景时会依据它自动同步（详见第三节）。

## 二、维护脚本

| 脚本 | 作用 |
|---|---|
| `fix_scene_asset_paths.py` | **批量修正场景里失效的资产路径**。用于解决打开布局时报「跳过 /wooden_lattice_tray_1，资产 …/basket_wood 不存在」这类错误（把已改名的资产 ID 映射回现存的包）。默认 dry-run，确认后加参数实际写入并自动备份。 |
| `fix_scene_package_ids.py` | 批量修正场景里的资产包 ID（package id）。 |
| `_pkg_check.py` | 检查场景引用的资产包是否都能在本地资产库中找到（巡检用）。 |

## 三、资产依赖（复现必读）

场景里出现的 `assets/e071469a36d3c8aa/<...>` 是 **OrcaLab 云资产库的虚拟路径**，
**不对应仓库里的真实目录**，也不随本仓库分发。

资产的真实来源是 OrcaLab 云平台的 `.pak` 包，由 OrcaStudio 按需下载到
`%LOCALAPPDATA%\Orca\OrcaStudio\<工程GUID>\user\downloaded_packages\`。

主场景 `SimpleMovement2.json` 的 `package_references` 声明了 5 个资产包：

| 包 ID（前缀） | 名称 | 作者 | 体积 |
|---|---|---|---|
| `fff12a1f` | SimpleMovement_Screw（桌面/场景底座） | Orca | ~455 MB |
| `2589f665` | g1_omnipicker（双臂协作服务机器人） | Orca | ~63 MB |
| `a284e930` | Medical（药盒 / 药瓶等 33 个资产） | Orca | ~33 MB |
| `3a46ef91` | simple_empty_kitchen（木格托盘所在包） | Orca | ~302 MB |
| `8c216d8b` | camera（相机资产） | Orca | ~3 KB |

> 复现前提：运行机已登录 **OrcaLab 账号**，且在资产库中**订阅**了上表 5 个包。
> 打开场景时 Studio 会自动拉取；若某个包未订阅，对应实体会被跳过，
> 表现为「跳过 /<实体名>，资产 <路径> 不存在」。

### ⚠️ 唯一例外：`SimpleMovement2_robot_cam.json`

该变体把机器人换成了 `g1_omnipicker_with_camera_usda`（**带相机**的 prefab）。
用 `fix_scene_asset_paths.py` 巡检会发现这条路径**不在云资产注册表里** ——
因为它属于**项目本地资产**（`assets/e071469a36d3c8aa/default_project/prefabs/`，
约 330 MB，被 `.gitignore` 排除），不在云端公共库。

也就是说：

| 场景 | 机器人 prefab | 资产来源 | 拿到仓库后能否直接加载 |
|---|---|---|---|
| `SimpleMovement2.json` | `g1_omnipicker_usda` | 云端包 `2589f665` | ✅ 订阅后自动下载 |
| `SimpleMovement2_robot_cam.json` | `g1_omnipicker_with_camera_usda` | **项目本地 assets/** | ⚠️ 需另行获取该 330 MB 资产目录 |

若甲方只需要复现**数据采集主流程**，用 `SimpleMovement2.json` 即可，无需本地资产。
`robot_cam` 变体是我们早期尝试「让机器人自带相机」时用的，需要本地资产到位。

## 四、用法

```powershell
# 1) 先巡检：列出场景里引用了但本地不存在的资产
& "<orcalab 环境>\python.exe" -X utf8 _pkg_check.py

# 2) 修资产路径（先跑 dry-run 看会改哪些，再实际写入）
& "<orcalab 环境>\python.exe" -X utf8 fix_scene_asset_paths.py --dry-run
& "<orcalab 环境>\python.exe" -X utf8 fix_scene_asset_paths.py --apply
```

> 两个 `fix_*` 脚本在写入前都会自动生成 `*.bak_<时间戳>` 备份，
> 回滚直接把备份改回原名即可。

## 五、注意

- `*.json.bak_*`、`*.json.mycamera_change_*` 等历史备份**未**纳入本仓库。
- 场景文件里的资产路径与包 ID 会随资产库变动，跨机器使用时先跑一遍
  `_pkg_check.py` 再跑 `fix_scene_asset_paths.py`。
- `SimpleMovement2_robot_cam.json` 由 `docs`/脚本于 2026-10-15 从旧 `layouts/` 目录
  迁入并修复（`basket_wood` → `basket_kitchen_01`，补 `package_references`）。
