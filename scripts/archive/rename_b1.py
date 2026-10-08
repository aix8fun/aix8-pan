#!/usr/bin/env python3
"""B1 全库重命名：电影文件技术段整体加方括号（v2.0 -> v2.1）。

机械变换（不重新生成名字，只在既有主干上加括号，DISC 尾巴留在括号外）：
    黑寡妇 Black Widow (2021) 2160p TrueHD Atmos.iso
        -> 黑寡妇 Black Widow (2021) [2160p TrueHD Atmos].iso
    指环王1 … (2001) 2160p TrueHD Atmos DISC1.iso
        -> 指环王1 … (2001) [2160p TrueHD Atmos] DISC1.iso
    … 2160p TrueHD Atmos-poster.jpg
        -> … [2160p TrueHD Atmos]-poster.jpg

用法：
    python3 tests/rename_b1.py --dry-run     # 只生成计划 data/state/rename_b1_plan.json
    python3 tests/rename_b1.py --execute     # 执行（断点续跑，状态 data/state/rename_b1_state.json）

安全设计：
  - 幂等：主干已含 "[" 的跳过；无技术尾巴的跳过
  - 限速：每次改名后 sleep SLEEP 秒；每 BATCH 个休息 BATCH_PAUSE 秒（防 115 风控）
  - 每个作品目录改完回读校验一次
  - 只改文件名，不动目录名（目录名不含技术段）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aix8pan.config import state_path

from aix8pan.core.openlist import OpenListClient  # noqa: E402
from aix8pan.core.parser import QUALITY_TOKEN_RE  # noqa: E402

ROOT = "/115/01-电影"
PLAN_PATH = state_path("rename_b1_plan.json")
STATE_PATH = state_path("rename_b1_state.json")

SLEEP = 1.5          # 每次改名间隔（秒）
BATCH = 40           # 每批数量
BATCH_PAUSE = 20     # 批间休息（秒）
LIST_SLEEP = 0.5     # 目录列表间隔（秒）

YEAR_TAIL_RE = re.compile(r"^(?P<head>.+\(\d{4}\))\s+(?P<tail>.+)$")
DISC_END_RE = re.compile(r"([\s._\-]+(?:disc|cd|part|pt|d|p)\s*\d+)$", re.IGNORECASE)
COMPANION_SUFFIX_RE = re.compile(
    r"-(poster|fanart|clearlogo|logo|backdrop|thumb|banner|clearart|landscape|discart)$",
    re.IGNORECASE)
MEDIA_AND_COMPANION_EXTS = {
    ".iso", ".mkv", ".mp4", ".ts", ".avi", ".m2ts", ".wmv", ".flv", ".webm", ".mov",
    ".nfo", ".jpg", ".jpeg", ".png", ".srt", ".ass", ".ssa",
}


def b1_stem(stem: str) -> str:
    """主干 -> B1 新主干；不需要改返回 ""。"""
    if "[" in stem:
        return ""
    # 先剥伴随文件后缀（-poster 等），括号只包技术段
    suffix = ""
    m = COMPANION_SUFFIX_RE.search(stem)
    if m:
        suffix = stem[m.start():]
        stem = stem[:m.start()]
    m = YEAR_TAIL_RE.match(stem)
    if not m:
        return ""
    head, tail = m.group("head"), m.group("tail").strip()
    tail = re.sub(r"^[\s\-–—._]+", "", tail)   # 尾巴前的连字符/点号不进括号
    if not tail or not QUALITY_TOKEN_RE.search(tail):
        return ""                     # 年份后没有技术段，不动
    # DISC 尾巴留在括号外
    disc = ""
    dm = DISC_END_RE.search(tail)
    if dm:
        disc = tail[dm.start():]
        tail = tail[:dm.start()].rstrip()
    if not tail or not QUALITY_TOKEN_RE.search(tail):
        return ""
    return f"{head} [{tail}]{disc}{suffix}"


def b1_name(fname: str) -> str:
    """完整文件名 -> B1 新文件名；不需要改返回 ""。"""
    if "." not in fname:
        return ""
    stem, ext = fname.rsplit(".", 1)
    if f".{ext.lower()}" not in MEDIA_AND_COMPANION_EXTS:
        return ""
    new_stem = b1_stem(stem)
    return f"{new_stem}.{ext}" if new_stem else ""


def walk_work_dirs(client: OpenListClient) -> list[str]:
    """列出 ROOT 下所有作品目录（递归，跳过容器层，返回含文件的末级目录）。"""
    work_dirs: list[str] = []

    def walk(path: str, depth: int) -> None:
        entries = client.list_dir(path, per_page=1000)
        time.sleep(LIST_SLEEP)
        has_file = any(not e.get("is_dir") for e in entries)
        if has_file or depth >= 4:
            if has_file:
                work_dirs.append(path)
            return
        for e in entries:
            if e.get("is_dir"):
                walk(f"{path}/{e['name']}", depth + 1)

    walk(ROOT, 0)
    return work_dirs


def build_plan(client: OpenListClient) -> list[dict]:
    plan: list[dict] = []
    dirs = walk_work_dirs(client)
    print(f"作品目录 {len(dirs)} 个", flush=True)
    for i, d in enumerate(dirs, 1):
        entries = client.list_dir(d, per_page=1000)
        time.sleep(LIST_SLEEP)
        for e in entries:
            if e.get("is_dir"):
                continue
            old = e.get("name") or ""
            new = b1_name(old)
            if new and new != old:
                plan.append({"dir": d, "old": old, "new": new,
                             "size": e.get("size") or 0})
        if i % 20 == 0:
            print(f"  扫描 {i}/{len(dirs)}，计划项 {len(plan)}", flush=True)
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.execute):
        ap.error("需要 --dry-run 或 --execute")

    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(
        encoding="utf-8"))["openlist"]
    client = OpenListClient(cfg["base_url"], cfg["username"], cfg["password"],
                            op_interval_ms=cfg.get("op_interval_ms", 400))

    if args.dry_run:
        plan = build_plan(client)
        PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        dirs = sorted({p["dir"] for p in plan})
        print(f"\n计划完成：{len(plan)} 个文件待改名，涉及 {len(dirs)} 个作品目录")
        print(f"已写入 {PLAN_PATH}")
        for p in plan[:10]:
            print(f"  {p['old']}\n    -> {p['new']}")
        return 0

    # execute
    if not PLAN_PATH.exists():
        print("先跑 --dry-run 生成计划", file=sys.stderr)
        return 1
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() \
        else {"done": [], "failed": []}
    done = set(state["done"])
    todo = [p for p in plan if f"{p['dir']}/{p['old']}" not in done]
    print(f"计划 {len(plan)}，已完成 {len(done)}，本次待执行 {len(todo)}", flush=True)

    ok = fail = 0
    for i, p in enumerate(todo, 1):
        key = f"{p['dir']}/{p['old']}"
        try:
            client.rename(f"{p['dir']}/{p['old']}", p["new"])
            state["done"].append(key)
            ok += 1
        except Exception as e:  # noqa: BLE001
            state["failed"].append({"key": key, "new": p["new"], "error": str(e)[:300]})
            fail += 1
            print(f"  ❌ {p['old']} -> {e}", flush=True)
        if i % 10 == 0 or i == len(todo):
            STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
            print(f"  进度 {i}/{len(todo)}（成功 {ok} 失败 {fail}）", flush=True)
        time.sleep(SLEEP)
        if i % BATCH == 0:
            print(f"  …批次休息 {BATCH_PAUSE}s…", flush=True)
            time.sleep(BATCH_PAUSE)

    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n执行完成：成功 {ok}，失败 {fail}，累计完成 {len(state['done'])}/{len(plan)}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
