# -*- coding: utf-8 -*-
"""修复场景 JSON 里"已经不存在"的 actor 资产路径（asset_path）。

背景（源码级结论，非猜测）
--------------------------
OrcaStudio 载入布局时走 `orcalab/scene_layout/scene_layout_helper_v3.py`
里的 `_collect_layout_requests()`：对每个 `AssetActor` 拿它的 `asset_path`
去问 `MetadataServiceRequestBus.get_asset_package_reference(asset_path, out)`。
该函数（实现在 `orcalab/asset_sync/asset_sync_service.py`）只做两次查表：

    if asset_path in self._asset_path_to_logical: ...       # 原样
    if asset_path + '.spawnable' in self._asset_path_to_logical: ...  # 补后缀
    # 都没有 -> out 为空

`_asset_path_to_logical` 由**当前订阅的资产包清单**（用户目录下的
`asset_sync_state.json` 里各包的 `assets[].asset_path`）构建。
查不到就 out 为空，上层于是打印：

    跳过 {path}, 资产{asset_path}不存在。

也就是说：**即使 `basket_wood.spawnable` 这个文件真的躺在 .pak 里，只要
它不在平台发布的资产清单里，引擎一样认为"不存在"。**

本脚本的作用
------------
把场景里那些"清单里已经查不到"的 asset_path，按 **actor 名 -> 资产名 ->
清单里的当前路径** 换成能查到的路径。

  actor 名 `wooden_lattice_tray_1`  ->  去掉结尾 `_<数字>`  ->  `wooden_lattice_tray`
  清单里 name=wooden_lattice_tray 的资产 asset_path =
      assets/e071469a36d3c8aa/simple_empty_kitchen/kitchen_night/prop/prefabs/basket_kitchen_01.spawnable

只做**字节级最小替换**（保留 CRLF 与文件长度外的其它字节不变），并且只在
"旧路径确实查不到 + 新路径确实查得到"时才动手。

用法
----
    python fix_scene_asset_paths.py                # 只检查，不写
    python fix_scene_asset_paths.py --apply        # 实际写入（自动备份）
    python fix_scene_asset_paths.py --apply SimpleMovement2.json
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_CANDIDATES = [
    r"C:\Users\86322\AppData\Local\Orca\OrcaStudio\{3DB8A56E-2458-4543-93A1-1A41756B97DA}\user\asset_sync_state.json",
]

ASSET_PATH_RE = re.compile(rb'"asset_path"\s*:\s*"([^"]*)"')
TRAIL_IDX_RE = re.compile(r"_\d+$")


def find_state():
    for p in STATE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 asset_sync_state.json")


def build_manifest(state_path):
    """返回 (known, by_name, by_base)。

    known   : {小写路径: (包名, 资产名, 原始路径)}   —— 含"去掉 .spawnable"的键
    by_name : {小写资产名: [(包名, 资产名, 路径), ...]}
    by_base : {小写文件名(去扩展名): [...]}
    """
    d = json.load(io.open(state_path, encoding="utf-8"))
    known, by_name, by_base = {}, {}, {}
    for p in d.get("logical_packages", []):
        pname = p.get("name")
        for a in p.get("assets") or []:
            ap = a.get("asset_path")
            if not ap:
                continue
            rec = (pname, a.get("name"), ap)
            low = ap.lower()
            known.setdefault(low, rec)
            if low.endswith(".spawnable"):
                known.setdefault(low[: -len(".spawnable")], rec)
            if a.get("name"):
                by_name.setdefault(a["name"].lower(), []).append(rec)
            base = os.path.basename(low)
            base = re.sub(r"\.[a-z0-9]+$", "", base)
            by_base.setdefault(base, []).append(rec)
    return known, by_name, by_base


def guess_new_path(old_path, actor_name, known, by_name, by_base):
    """按 actor 名 -> 资产名 找清单里的当前路径；找不到再退回按文件名找。"""
    # 1) actor 名去掉结尾 _<数字>
    cand_names = []
    if actor_name:
        base = TRAIL_IDX_RE.sub("", actor_name)
        cand_names.append(base)
        cand_names.append(actor_name)
    for n in cand_names:
        hits = by_name.get(n.lower())
        if hits:
            return hits[0]
    # 2) 退回：按旧路径的文件名（basket_wood -> basket_wood 查不到就放弃）
    old_base = os.path.basename(old_path)
    old_base = re.sub(r"\.[a-z0-9]+$", "", old_base).lower()
    hits = by_base.get(old_base)
    if hits:
        return hits[0]
    return None


def scan(path, known, by_name, by_base, apply=False):
    """返回 [(old, new, actor, pkg, asset_name), ...]；apply 时实际写入。"""
    raw = open(path, "rb").read()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception as e:
        print("  !! JSON 解析失败：%s" % e)
        return []

    # actor 路径 -> actor 名
    name_of = {}
    for a in doc.get("actors") or []:
        if a.get("path"):
            name_of[a["path"]] = a.get("name")

    # 找出所有未注册的 asset_path，并猜测它属于哪个 actor
    pending = {}
    for m in ASSET_PATH_RE.finditer(raw):
        ap = m.group(1).decode("utf-8", "replace")
        if ap.lower() in known:
            continue
        pending.setdefault(ap, [])

    if not pending:
        return []

    # 用 actor 名给每个未注册路径配一个"宿主 actor"
    for a in doc.get("actors") or []:
        ap = (a.get("asset_path") or "")
        if ap in pending:
            pending[ap].append(a.get("name"))

    out = []
    for ap, hosts in pending.items():
        actor = hosts[0] if hosts else None
        hit = guess_new_path(ap, actor, known, by_name, by_base)
        if not hit:
            out.append((ap, None, actor, None, None))
            continue
        pkg, asset_name, new_ap = hit
        # 场景里其余引用都不带扩展名，这里也去掉，保持文件风格一致
        if new_ap.lower().endswith(".spawnable"):
            new_ap = new_ap[: -len(".spawnable")]
        out.append((ap, new_ap, actor, pkg, asset_name))

    if apply and any(n for _, n, _, _, _ in out):
        bak = "%s.bak_assetpath_%s" % (path, time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(path, bak)
        buf = raw
        for old, new, _, _, _ in out:
            if new:
                buf = buf.replace(old.encode("utf-8"), new.encode("utf-8"))
        with open(path, "wb") as f:
            f.write(buf)
        print("  [写入] 备份 %s" % os.path.basename(bak))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="场景 json；不给则扫描本目录全部 *.json")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认只检查）")
    args = ap.parse_args()

    state = find_state()
    known, by_name, by_base = build_manifest(state)
    print("资产清单：%d 条路径（含去 .spawnable 别名）" % len(known))
    print("来源：%s" % state)
    print()

    files = args.files or sorted(
        f for f in os.listdir(HERE)
        if f.endswith(".json") and ".bak" not in f
    )

    bad = 0
    fixed = 0
    for fn in files:
        path = fn if os.path.isabs(fn) else os.path.join(HERE, fn)
        if not os.path.exists(path):
            print("== %s 不存在，跳过" % fn)
            continue
        rows = scan(path, known, by_name, by_base, apply=args.apply)
        if not rows:
            print("== %-30s OK（asset_path 全部在清单里）" % os.path.basename(path))
            continue
        print("== %-30s 发现 %d 处清单里查不到的 asset_path：" % (os.path.basename(path), len(rows)))
        for old, new, actor, pkg, an in rows:
            if new:
                fixed += 1
                print("     actor=%-26s %s" % (actor, "可修"))
                print("        旧: %s" % old)
                print("        新: %s     (%s / %s)" % (new, pkg, an))
            else:
                bad += 1
                print("     actor=%-26s %s" % (actor, "!! 猜不到替代路径，需人工确认"))
                print("        旧: %s" % old)
    print()
    print("可修复 %d 处，无法自动判定 %d 处%s"
          % (fixed, bad, "；已写入" if args.apply else "（未写入，加 --apply 生效）"))


if __name__ == "__main__":
    main()
