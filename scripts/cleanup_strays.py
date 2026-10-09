"""修复遗留散目录 + 清扫空旧目录（02-剧集 严格归一的收尾工具）。

用法:
    python3 scripts/cleanup_strays.py rename-strays   # 修正畸形季目录名（伪装者/唐朝诡事录）
    python3 scripts/cleanup_strays.py sweep           # 删除「递归为空」的旧式作品目录

安全:
- sweep 只删「整棵子树没有任何文件」的目录；有文件的目录原样保留并打印清单。
- 删除前先强刷复核一次。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.config import load_config
from aix8pan.core.openlist import OpenListClient

TV_ROOT = "/115/02-剧集"


def get_client() -> OpenListClient:
    cfg = load_config()
    ol = cfg["openlist"]
    return OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])


def rename_strays(client: OpenListClient) -> None:
    pairs = [
        (f"{TV_ROOT}/伪装者 (2015)/ Season 1", "Season 1"),
        (f"{TV_ROOT}/唐朝诡事录 (2022)/Session 3", "Season 3"),
    ]
    for path, new_name in pairs:
        try:
            client.rename(path, new_name)
            print(f"[OK] {path} -> {new_name}", flush=True)
        except Exception as e:
            print(f"[FAIL] {path}: {e}", flush=True)


def _tree_has_file(client: OpenListClient, path: str, depth: int = 0) -> tuple[bool, list[str]]:
    """递归检查目录树是否含文件。返回 (has_file, 样本文件路径)。"""
    if depth > 3:
        return True, [f"{path}/... (超深，保守视为有文件)"]
    try:
        items = client.list_all(path, refresh=True) or []
    except Exception:
        return True, [f"{path} (列出失败，保守视为有文件)"]
    samples: list[str] = []
    for e in items:
        name = e.get("name") or ""
        if not name:
            continue
        if e.get("is_dir"):
            has, sub = _tree_has_file(client, f"{path}/{name}", depth + 1)
            if has:
                samples.extend(sub)
        else:
            samples.append(f"{path}/{name}")
    return bool(samples), samples[:5]


def sweep(client: OpenListClient) -> None:
    entries = client.list_all(TV_ROOT, refresh=True) or []
    old_dirs = [e["name"] for e in entries
                if e.get("is_dir") and "{tmdbid-" not in (e.get("name") or "")
                and not (e.get("name") or "").startswith(("0-", "合集", "专辑"))]
    print(f"旧式目录候选 {len(old_dirs)} 个", flush=True)
    removed = kept = 0
    for name in old_dirs:
        path = f"{TV_ROOT}/{name}"
        has_file, samples = _tree_has_file(client, path)
        if has_file:
            kept += 1
            print(f"[保留] {path} 内有文件:", flush=True)
            for s in samples:
                print(f"       {s}", flush=True)
            continue
        try:
            # 复核为空后删除
            client.remove(TV_ROOT, [name])
            removed += 1
            print(f"[删除] {path}（空壳）", flush=True)
        except Exception as e:
            kept += 1
            print(f"[FAIL] {path}: {e}", flush=True)
    print(f"完成：删除 {removed} / 保留 {kept}", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    client = get_client()
    if cmd == "rename-strays":
        rename_strays(client)
    elif cmd == "sweep":
        sweep(client)
    else:
        print(__doc__)
        raise SystemExit(2)
