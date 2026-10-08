#!/usr/bin/env python3
"""对比容器现状与 container_scan 缓存，找出新增/消失的作品目录（只读）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.paths import state_path
from aix8pan.auditor import Auditor  # noqa: E402

a = Auditor()
cached = {r["path"] for r in
          json.loads(state_path("container_scan.json").read_text(encoding="utf-8"))["rows"]}

current: set[str] = set()
for root in ("/115/01-电影/合集", "/115/01-电影/专辑"):
    works = a._find_works(root, include_containers=True, max_depth=6)
    current.update(works)
    print(f"{root}: {len(works)} 部", flush=True)

new = sorted(current - cached)
gone = sorted(cached - current)
print(f"\n新增 {len(new)} 部：")
for p in new:
    print("  +", p)
print(f"消失 {len(gone)} 部：")
for p in gone:
    print("  -", p)

# 顺便看 0-待整理 和根目录散件
print("\n0-待整理：")
try:
    for e in a.client.list_all("/115/01-电影/0-待整理", refresh=True):
        print("  ", "[D]" if e.get("is_dir") else "   ", e["name"])
except Exception as ex:  # noqa: BLE001
    print("  (读取失败:", ex, ")")
print("\n根目录散件：")
for e in a.client.list_all("/115/01-电影", refresh=True):
    if not e.get("is_dir"):
        print("  ", e["name"])
