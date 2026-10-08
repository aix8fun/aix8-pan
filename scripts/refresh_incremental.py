#!/usr/bin/env python
"""增量刷新管线：局部变更后快速重建核对表，替代 13 分钟的全链路。

用法:
    python scripts/refresh_incremental.py --sync <作品路径>... [--drop <旧路径>...]
                                        [--refresh-collections] [--no-report]

参数:
    --sync   需要重扫的作品目录现状路径（新归位/改名/新增后）
    --drop   需要移除的旧路径（移动/改名前路径、已删除作品）
    --refresh-collections  强制重取全部 TMDB 合集详情（合集成员变动时）
    --no-report  只更新缓存，不重新生成 xlsx

流程（全部增量）:
    scan_containers --sync/--drop  →  fetch_tmdb_collections --incremental
    →  fetch_115_cids --incremental  →  make_report2

前提: 已跑过一次全量（data/state/container_scan.json、data/state/tmdb_collections.json、
data/state/115_cids.json 存在）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PY = sys.executable


def run(script: str, args: list[str]) -> int:
    cmd = [PY, str(TESTS / script), *args]
    print(f"\n$ {' '.join([script, *args])}", flush=True)
    return subprocess.call(cmd)


def main() -> int:
    argv = sys.argv[1:]
    sync: list[str] = []
    drop: list[str] = []
    refresh_colls = "--refresh-collections" in argv
    no_report = "--no-report" in argv
    i = 0
    while i < len(argv):
        if argv[i] == "--sync":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                sync.append(argv[i])
                i += 1
        elif argv[i] == "--drop":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                drop.append(argv[i])
                i += 1
        else:
            i += 1

    if not sync and not drop:
        print("❌ 至少给一个 --sync 或 --drop 路径（全量刷新请直接跑原脚本）")
        return 2

    rc = run("scan_containers.py",
             (["--sync", *sync] if sync else []) + (["--drop", *drop] if drop else []))
    if rc:
        return rc

    args = ["--incremental"] + (["--refresh-collections"] if refresh_colls else [])
    rc = run("fetch_tmdb_collections.py", args)
    if rc:
        return rc

    rc = run("fetch_115_cids.py", ["--incremental"])
    if rc:
        print("⚠️ cids 增量解析失败，链接列可能留空（不阻断报表）")

    if not no_report:
        rc = run("make_report2.py", [])
    print("\n== 增量刷新完成 ==")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
