#!/usr/bin/env python
"""只读列出「0-待整理」区，解析出其中的 TMDB id，供核对表区分
「已上映但网盘真的没有」与「已下载、只是还没归位」。

产出 data/state/inbox.json   —— 不写网盘、不修改任何文件。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.config import state_path

from aix8pan.config import load_config          # noqa: E402
from aix8pan.core.openlist import OpenListClient     # noqa: E402
from aix8pan.core.parser import parse_media_name     # noqa: E402

OUT = state_path("inbox.json")
DIRS = ["/115/01-电影/0-待整理"]


def main() -> int:
    cfg = load_config()
    ol = cfg["openlist"]
    c = OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
    items = []
    for d in DIRS:
        for e in c.list_all(d, refresh=True):
            name = e.get("name") or ""
            q = parse_media_name(name, is_dir=bool(e.get("is_dir")))
            items.append({
                "dir": d,
                "name": name,
                "is_dir": bool(e.get("is_dir")),
                "tmdb_id": str(q.tmdb_id or ""),
                "title": q.title or "",
                "year": q.year or "",
            })
            print(f"  {'DIR ' if e.get('is_dir') else 'FILE'} {name}  → tmdb {q.tmdb_id or '—'}")
    OUT.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dirs": DIRS,
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}  条目 {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
