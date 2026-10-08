#!/usr/bin/env python3
"""整理 01-电影根目录散落的 5 部作品：规范命名 → 移到 合集/专辑。

用法:
    python scripts/archive/fix_strays.py --dry-run    # 只打印计划
    python scripts/archive/fix_strays.py --execute    # 执行（限速）

归位方案（TMDB 已确认）:
    年会不能停！ (1173076) + 年会不能停！2 (1541125)
        → 合集/年会不能停！（系列）/      (TMDB collection 1713484)
    欢迎来龙餐馆 (1391021) / 功夫女足 (1491920) / 八仙！ (1633056)
        → 专辑/

每部的操作（同目录 rename，115 实测安全）:
    1. 主文件去 {tmdb-N}、技术段按 B1 进方括号（标题按国产片惯例双写）
    2. poster.jpg / fanart.jpg / logo.png → {stem}-poster/-fanart/-clearlogo
    3. movie.nfo → {stem}.nfo（八仙保留更富的旧命名 nfo，删精简 movie.nfo）
    4. 目录 {tmdb-} → {tmdbid-}
    5. 移动到目标容器（需要时先 mkdir）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aix8pan.openlist import OpenListClient  # noqa: E402

ROOT = "/115/01-电影"
OP_SLEEP = 1.6          # 每次写操作间隔（防风控）

# (现目录名, tmdb_id, 标题, 年份, 主文件现名, 技术段, 目标容器, nfo来源)
WORKS = [
    {
        "folder": "年会不能停！2 (2026) {tmdb-1541125}",
        "folder_new": "年会不能停！2 (2026) {tmdbid-1541125}",
        "title": "年会不能停！2", "year": "2026",
        "main": "年会不能停！2 (2026) {tmdb-1541125} [2160p].mkv",
        "tech": "2160p",
        "target": "/115/01-电影/合集/年会不能停！（系列）",
        "nfo_source": "movie.nfo",           # 重命名保留内容
        "deletes": [],
    },
    {
        "folder": "年会不能停！ (2023) {tmdb-1173076}",
        "folder_new": "年会不能停！ (2023) {tmdbid-1173076}",
        "title": "年会不能停！", "year": "2023",
        "main": "年会不能停！ (2023) {tmdb-1173076} [2160p H.265].mp4",
        "tech": "2160p H.265",
        "target": "/115/01-电影/合集/年会不能停！（系列）",
        "nfo_source": "movie.nfo",
        "deletes": [],
    },
    {
        "folder": "欢迎来龙餐馆 (2026) {tmdb-1391021}",
        "folder_new": "欢迎来龙餐馆 (2026) {tmdbid-1391021}",
        "title": "欢迎来龙餐馆", "year": "2026",
        "main": "欢迎来龙餐馆 (2026) {tmdb-1391021} [1080p H.265 AAC 2.0].mp4",
        "tech": "1080p H.265 AAC 2.0",
        "target": "/115/01-电影/专辑",
        "nfo_source": "movie.nfo",
        "deletes": [],
    },
    {
        "folder": "功夫女足 (2026) {tmdb-1491920}",
        "folder_new": "功夫女足 (2026) {tmdbid-1491920}",
        "title": "功夫女足", "year": "2026",
        "main": "功夫女足 (2026) {tmdb-1491920} [2160p H.265 FLAC].mkv",
        "tech": "2160p H.265 FLAC",
        "target": "/115/01-电影/专辑",
        "nfo_source": "movie.nfo",
        "deletes": [],
    },
    {
        "folder": "八仙！ (2026) {tmdb-1633056}",
        "folder_new": "八仙！ (2026) {tmdbid-1633056}",
        "title": "八仙！", "year": "2026",
        "main": "八仙！ (2026) {tmdb-1633056} [1080p].mkv",
        "tech": "1080p",
        "target": "/115/01-电影/专辑",
        # 旧命名 nfo 是 6.9KB 富信息版 → 重命名为规范名；movie.nfo(1KB 精简) 删除
        "nfo_source": "八仙！ (2026) {tmdb-1633056} [1080p].nfo",
        "deletes": ["movie.nfo", "backdrop.jpg"],   # backdrop 与 fanart 同尺寸重复
    },
]


def build_plan(w: dict) -> list[tuple[str, str, str]]:
    """返回 [(op, src_name, dst_name)]，op ∈ rename/delete/mkdir/move。"""
    stem = f"{w['title']} {w['title']} ({w['year']}) [{w['tech']}]"
    ext = w["main"].rsplit(".", 1)[-1]
    ops: list[tuple[str, str, str]] = []
    ops.append(("rename", w["main"], f"{stem}.{ext}"))
    ops.append(("rename", "poster.jpg", f"{stem}-poster.jpg"))
    ops.append(("rename", "fanart.jpg", f"{stem}-fanart.jpg"))
    ops.append(("rename", "logo.png", f"{stem}-clearlogo.png"))
    ops.append(("rename", w["nfo_source"], f"{stem}.nfo"))
    for d in w["deletes"]:
        ops.append(("delete", d, ""))
    ops.append(("rename_dir", w["folder"], w["folder_new"]))
    ops.append(("move", w["folder_new"], w["target"]))
    return ops


def main() -> int:
    execute = "--execute" in sys.argv
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json")
                     .read_text(encoding="utf-8"))["openlist"]
    client = OpenListClient(cfg["base_url"], cfg["username"], cfg["password"],
                            op_interval_ms=cfg["op_interval_ms"])

    mode = "执行" if execute else "DRY-RUN"
    print(f"== {mode} ==", flush=True)
    made_dirs: set[str] = set()
    n_ok = n_fail = 0

    for w in WORKS:
        cur_dir = f"{ROOT}/{w['folder']}"
        ops = build_plan(w)
        print(f"\n■ {w['folder']} → {w['target'].replace(ROOT + '/', '')}/", flush=True)
        for op, src, dst in ops:
            print(f"   {op:10s} {src}" + (f"  →  {dst}" if dst else ""), flush=True)
        if not execute:
            continue

        # 执行前确认目录存在且文件齐全
        try:
            names = {e["name"] for e in client.list_all(cur_dir, refresh=True)}
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ 目录读取失败，跳过: {e}", flush=True)
            n_fail += 1
            continue
        for op, src, dst in ops:
            try:
                if op == "rename":
                    if src not in names:
                        print(f"   ⚠ 源不存在，跳过: {src}", flush=True)
                        continue
                    if dst in names:
                        print(f"   ⚠ 目标已存在，跳过: {dst}", flush=True)
                        continue
                    client.rename(f"{cur_dir}/{src}", dst)
                    names.discard(src)
                    names.add(dst)
                elif op == "delete":
                    if src in names:
                        client.remove(cur_dir, [src])
                        names.discard(src)
                elif op == "rename_dir":
                    client.rename(cur_dir, dst)
                    cur_dir = f"{ROOT}/{dst}"
                elif op == "move":
                    if dst not in made_dirs:
                        client.ensure_dir(dst)
                        made_dirs.add(dst)
                        time.sleep(OP_SLEEP)
                    client.move(ROOT, [src], dst)
                n_ok += 1
                time.sleep(OP_SLEEP)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                print(f"   ❌ {op} {src}: {e}", flush=True)
                time.sleep(OP_SLEEP * 2)
        if execute:
            # 回读验证
            try:
                final = {e["name"]
                         for e in client.list_all(f"{w['target']}/{w['folder_new']}",
                                                  refresh=True)}
                stem = f"{w['title']} {w['title']} ({w['year']}) [{w['tech']}]"
                want = {f"{stem}.{w['main'].rsplit('.', 1)[-1]}",
                        f"{stem}-poster.jpg", f"{stem}-fanart.jpg",
                        f"{stem}-clearlogo.png", f"{stem}.nfo"}
                missing = want - final
                extra_legacy = {x for x in final
                                if x in ("poster.jpg", "fanart.jpg", "logo.png",
                                         "movie.nfo", "backdrop.jpg")}
                if missing or extra_legacy:
                    print(f"   ⚠ 回读异常: 缺 {missing or '无'} / 残留 {extra_legacy or '无'}",
                          flush=True)
                    n_fail += 1
                else:
                    print(f"   ✅ 回读验证通过（{len(final)} 个文件）", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"   ❌ 回读失败: {e}", flush=True)
                n_fail += 1

    print(f"\n== 完成: 成功 {n_ok} 步, 失败 {n_fail} 步 ==", flush=True)
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
