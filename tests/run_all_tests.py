# -*- coding: utf-8 -*-
"""一键跑全部离线测试。"""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 采集模块已归到 scripts/collect（被测试的模块都从这里导入）
COLLECT = os.path.join(ROOT, "scripts", "collect")
PY = sys.executable
tests = [
    "test_recorder.py",
    "test_keymap.py",
    "test_saver.py",
    "test_saver_lerobot.py",
    "demo_offline.py",
]

total_ok = total_fail = 0
for t in tests:
    print("=" * 62)
    print("RUN", t)
    print("=" * 62)
    r = subprocess.run([PY, "-X", "utf8", os.path.join(HERE, t)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=HERE, env={**os.environ, "PYTHONPATH": COLLECT + os.pathsep + ROOT})
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if "passed" in line and "failed" in line:
            print("   ", line.strip())
            try:
                p = line.split(":")[1].strip()
                o, f = p.replace("passed", "").replace("failed", "").split(",")
                total_ok += int(o); total_fail += int(f)
            except Exception:
                pass
        elif "FAIL" in line or r.returncode != 0 and line.strip():
            print("   ", line.strip())
    print()

print("=" * 62)
print(f"总计: {total_ok} passed, {total_fail} failed")
print("=" * 62)
