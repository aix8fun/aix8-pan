"""检测 / 修复 115 网盘上的「同名重复条目」。

背景（2026-10-07 沙盒实测结论）
────────────────────────────────────────────────────────────
1. 115 **允许**同一目录下存在多个**完全同名**的文件；
2. 对已存在路径直接 `PUT /api/fs/upload` **不覆盖**，而是**再建一个同名条目**；
3. OpenList 的 `/api/fs/list` 会把同名条目**折叠成一条**（只返回其中一个），
   所以重复在接口侧几乎不可见 —— **只有 115 网页端能看到两条**；
   这正是「网页里有两个同名 nfo、脚本却只看到一个」的原因。

修复思路
────────────────────────────────────────────────────────────
平台的 `/api/fs/remove` 是按**名字**删除，一次只删掉其中一条。于是：

    下载当前可见的那条 → remove（藏着的另一条浮出）→
    若浮出来的同名条目仍在：下载它 → 再 remove → 直到该名字消失 →
    把体积较大的那份重新上传

结果：目录里只剩一条，且保留的是信息量更大的那一版。

⚠️ 不能用「改名探针」来检测：OpenList 的 115 驱动不按全名改名（只取新名的基名
+ 源文件扩展名），跨扩展名改名会静默产出错名文件。

用法：
    python scripts/dedupe_same_name.py                  # 默认检查两个 nfo 目录（只读）
    python scripts/dedupe_same_name.py --execute        # 执行修复
    python scripts/dedupe_same_name.py "<目录>" ["<目录>/<文件名>"] ... [--execute]
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.config import load_config
from aix8pan.core.openlist import OpenListClient

MOV = "/115/01-电影"

# 默认目标：2026-10-07 那次「刷新 nfo 中文标题」实验误伤的两个目录
DEFAULT_TARGETS = [
    f"{MOV}/专辑/黑寡妇 (2021) {{tmdbid-497698}}",
    f"{MOV}/合集/漫威宇宙（主线）/蜘蛛侠（复仇者联盟）（系列）/"
    "蜘蛛侠：英雄无归 (2021) {tmdbid-634649}",
]

MAX_BYTES = 8 * 1024 * 1024         # 安全阀：只处理小体积伴随文件，绝不下载 iso


def entries(c: OpenListClient, folder: str) -> list[dict]:
    return c.list_all(folder, refresh=True)


def named(c: OpenListClient, folder: str, name: str) -> list[dict]:
    return [e for e in entries(c, folder) if (e.get("name") or "") == name]


def fetch(c: OpenListClient, folder: str, name: str) -> bytes:
    url = c.get_download_url(f"{folder}/{name}")
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def pick_nfo(c: OpenListClient, folder: str) -> list[str]:
    """目录里的 nfo（不含剧集 tvshow.nfo 之外的复杂情况，够用）。"""
    return [e["name"] for e in entries(c, folder)
            if (e.get("name") or "").lower().endswith(".nfo") and not e.get("is_dir")]


def repair_one(c: OpenListClient, folder: str, name: str, execute: bool) -> dict:
    shown = named(c, folder, name)
    if not shown:
        return {"name": name, "status": "不存在"}
    cur = shown[0]
    size = cur.get("size") or 0
    if size > MAX_BYTES:
        return {"name": name, "status": f"跳过大文件 ({size:,} B)"}
    if not execute:
        return {"name": name, "status": "待检测（加 --execute 才会下载并修复）",
                "shown_size": size}

    keep: bytes = fetch(c, folder, name)
    size = len(keep)
    rounds = []
    for _ in range(3):                       # 最多删 3 轮（正常情况下 ≤2 轮）
        c.remove(folder, [name])
        time.sleep(0.8)
        left = named(c, folder, name)
        if not left:
            break
        sz = left[0].get("size") or 0
        rounds.append(sz)
        if sz > MAX_BYTES:
            break
        blob = fetch(c, folder, name)        # 浮出来的同名条目
        if len(blob) > len(keep):
            keep = blob
    else:
        return {"name": name, "status": "同名条目过多，已停止（请人工处理）",
                "others": rounds}

    # 把保留的那份传回去
    c.upload(f"{folder}/{name}", keep, overwrite=True)
    time.sleep(0.8)
    final = named(c, folder, name)
    return {"name": name, "status": "已修复" if not rounds else "已修复（发现并清除了同名重复）",
            "shown_size": size, "kept_size": len(keep), "dup_found": rounds,
            "final": [e.get("size") for e in final]}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    execute = "--execute" in sys.argv
    targets = args or DEFAULT_TARGETS

    cfg = load_config()
    ol = cfg["openlist"]
    c = OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])

    for t in targets:
        if "/" in t and not t.startswith("/"):
            t = "/" + t
        # "目录/文件名" 形式：最后一段含扩展名则视为文件名
        if Path(t).suffix and not t.endswith("/"):
            folder, name = t.rsplit("/", 1)
            files = [name]
        else:
            folder, files = t, pick_nfo(c, t)
        print(f"\n■ {folder}")
        if not c.exists(folder):
            print("   ⤵ 目录不存在，跳过")
            continue
        for f in files:
            r = repair_one(c, folder, f, execute)
            print(f"   {r['name']}")
            print(f"      {r['status']}")
            if r.get("dup_found"):
                print(f"      可见 {r.get('shown_size', '?')} → 清除了同名重复 "
                      f"{r['dup_found']}，保留 {r['kept_size']:,} B")
            if r.get("final"):
                print(f"      复验：剩 {len(r['final'])} 条 {r['final']}")

    if not execute:
        print("\n（只读未改动任何文件。加 --execute 执行修复）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
