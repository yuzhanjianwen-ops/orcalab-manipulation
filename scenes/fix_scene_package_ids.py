# -*- coding: utf-8 -*-
"""修复场景 JSON 里"陈旧/变更过"的资产包 id。

背景
----
OrcaStudio 的场景文件用 `package_references` 记录它引用了哪些资产包：

    "package_references": [
        { "id": "<逻辑包 id>", "name": "<包名>" }, ...
    ]

平台给同一个包换过一次"逻辑 id"之后（例如 simple_empty_kitchen 的
逻辑 id 由 d940b2b4-... 变成 3a46ef91-...，而 .pak 文件名仍是 d940b2b4-...），
老场景里存的还是旧 id，引擎按 id 找不到已订阅的包 → 场景打不开。

本脚本的作用
------------
读 `asset_sync_state.json`（引擎当前的包注册表），为每个逻辑包建立
「历史别名 -> 当前逻辑 id」的映射，然后**只做最小文本替换**：
仅替换 package_references 里那些 {id, name} 中 id 陈旧、但 name 能对上的条目。
不动其它任何字节（不重新序列化整个 JSON，避免引擎解析出意外差异）。

用法
----
    python fix_scene_package_ids.py                 # 只检查，不写
    python fix_scene_package_ids.py --apply         # 实际写入（自动备份）
    python fix_scene_package_ids.py --apply SimpleMovement2.json
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

# 匹配 { "id": "<36位>", "name": "<...>" }（字节模式，保留原文件换行/编码）
PAIR_RE = re.compile(
    rb'("id"\s*:\s*")([0-9a-fA-F-]{36})("\s*,\s*"name"\s*:\s*")([^"]+)("\s*\})',
    re.S,
)


def find_state():
    for p in STATE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 asset_sync_state.json")


def build_alias_map(state_path):
    """返回 (by_name, alias->logical_id)。alias 包括旧 id / pak 文件名 / base_package_id。"""
    d = json.load(io.open(state_path, encoding="utf-8"))
    by_name, alias = {}, {}
    for p in d.get("logical_packages", []):
        lid = p["id"]
        name = p["name"]
        by_name[name] = lid
        bp = p.get("base_package") or {}
        for a in (bp.get("package_id"), bp.get("base_package_id"),
                  (bp.get("file_name") or "").replace(".pak", ""),
                  bp.get("ref_logical_id")):
            if a and a != lid:
                alias[a] = (lid, name)
    return by_name, alias


def fix_file(path, by_name, alias, apply=False):
    """字节级最小替换：只改那个 id 字符串，换行(CRLF)/其余字节原样保留。"""
    raw = open(path, "rb").read()
    changes = []

    def repl(m):
        pre, pid, mid, name, post = m.groups()
        pid_s = pid.decode("ascii")
        name_s = name.decode("utf-8")
        want = by_name.get(name_s)
        if not want or want == pid_s:
            return m.group(0)
        # 只有该 id 确实是这个包的历史别名，才替换
        if alias.get(pid_s, (None,))[0] == want:
            changes.append((pid_s, want, name_s))
            return pre + want.encode("ascii") + mid + name + post
        return m.group(0)

    out = PAIR_RE.sub(repl, raw)
    if changes and apply:
        bak = "%s.bak_pkgid_%s" % (path, time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(path, bak)
        with open(path, "wb") as f:
            f.write(out)
        print("  [写入] %s  (备份 %s)" % (os.path.basename(path), os.path.basename(bak)))
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="场景 json；不给则扫描本目录全部 *.json")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认只检查）")
    args = ap.parse_args()

    state = find_state()
    by_name, alias = build_alias_map(state)
    print("引擎注册表:", os.path.basename(os.path.dirname(os.path.dirname(state))))
    print("逻辑包 %d 个；历史别名 %d 条" % (len(by_name), len(alias)))
    for a, (lid, nm) in sorted(alias.items()):
        print("   别名 %s  ->  %s  (%s)" % (a, lid, nm))
    print()

    files = args.files or sorted(
        f for f in os.listdir(HERE)
        if f.endswith(".json") and ".bak" not in f
    )

    total = 0
    for fn in files:
        path = fn if os.path.isabs(fn) else os.path.join(HERE, fn)
        if not os.path.exists(path):
            print("== %s  不存在，跳过" % fn); continue
        try:
            io.open(path, encoding="utf-8").read()
        except Exception as e:
            print("== %s  读取失败 %s" % (fn, e)); continue
        ch = fix_file(path, by_name, alias, apply=args.apply)
        if ch:
            total += len(ch)
            print("== %s  需要修复 %d 处：" % (os.path.basename(path), len(ch)))
            for old, new, nm in ch:
                print("     %-26s : %s -> %s" % (nm, old, new))
        else:
            print("== %s  OK" % os.path.basename(path))

    print()
    print("共 %d 处%s" % (total, "，已写入" if args.apply else "（未写入，加 --apply 生效）"))


if __name__ == "__main__":
    main()
