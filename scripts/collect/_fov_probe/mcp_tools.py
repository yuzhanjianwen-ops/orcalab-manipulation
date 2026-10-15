# -*- coding: utf-8 -*-
import os, sys, io, json
sys.path.insert(0, r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from orca_mcp import OrcaMcp, call_text
m = OrcaMcp()
print("serverInfo:", m.connect())
ts = m.tools()
print("n_tools:", len(ts))
for t in ts:
    print("  -", t.get("name"))