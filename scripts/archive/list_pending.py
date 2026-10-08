#!/usr/bin/env python3
"""列出 0-待整理 下所有作品目录及文件。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aix8pan.core.openlist import OpenListClient  # noqa: E402

cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json")
                 .read_text(encoding="utf-8"))["openlist"]
c = OpenListClient(cfg["base_url"], cfg["username"], cfg["password"],
                   op_interval_ms=cfg["op_interval_ms"])
base = "/115/01-电影/0-待整理"
for d in c.list_all(base, refresh=True):
    if not d.get("is_dir"):
        print("FILE", d["name"])
        continue
    print("■", d["name"])
    for f in c.list_all(base + "/" + d["name"], refresh=True):
        tag = "[D] " if f.get("is_dir") else "    "
        print("  ", tag, f["name"], f.get("size", 0))
