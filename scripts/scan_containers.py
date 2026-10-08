#!/usr/bin/env python
"""扫描「合集 / 专辑」容器下的全部作品，输出结构化 JSON（**只读**）。

用法:
    python scripts/scan_containers.py            # 全部（合集 + 专辑）
    python scripts/scan_containers.py 专辑        # 只扫某类

增量模式（局部变更后刷新缓存，避免全库重扫）:
    python scripts/scan_containers.py --sync <作品目录路径> [<路径>...] [--drop <旧路径>...]
        --sync  重新扫描这些作品目录（新归位/改名后的现状路径），结果合并进缓存
        --drop  从缓存移除这些路径（移动/改名前的旧路径、已删除的作品）
    增量模式要求 data/state/container_scan.json 已存在（先跑过一次全量）。

输出: data/state/container_scan.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.config import state_path

from aix8pan.core import naming_spec as spec
from aix8pan.pipeline.auditor import TMDB_ANY_RE, Auditor
from aix8pan.core.naming import NamingEngine
from aix8pan.core.parser import parse_media_name
from aix8pan.pipeline.planner import SEASON_DIR_RE

ROOTS = [
    ("/115/01-电影/合集", "合集"),
    ("/115/01-电影/专辑", "专辑"),
]
DEST = state_path("container_scan.json")


def rel_container(work: str, root: str) -> str:
    """作品相对分类根的容器路径（不含作品自身），如 合集/漫威宇宙（主线）/钢铁侠（系列）。"""
    r = work[len(root.rstrip("/")):].lstrip("/")
    parts = r.split("/")
    cat = root.rstrip("/").split("/")[-1]
    if len(parts) <= 1:
        return cat
    return cat + "/" + "/".join(parts[:-1])


def root_of(path: str) -> tuple[str, str] | None:
    """按路径前缀判断作品属于哪个分类根。"""
    for root, cat in ROOTS:
        if path == root or path.startswith(root.rstrip("/") + "/"):
            return root, cat
    return None


def scan_work(a: Auditor, eng: NamingEngine, w: str, root: str, cat: str) -> dict:
    """扫描单个作品目录，产出一行结构化记录。"""
    folder = w.rstrip("/").split("/")[-1]
    kind = a._kind(w, "auto")
    entries = a.client.list_all(w, refresh=True)
    p = parse_media_name(folder, is_dir=True)
    m = TMDB_ANY_RE.search(folder)
    tmdb_id = m.group(2) if m else ""
    id_tag_raw = m.group(0) if m else ""

    media, companions, season_dirs = [], [], []
    dir_file_count = 0
    for e in entries:
        n = e.get("name") or ""
        if e.get("is_dir"):
            if SEASON_DIR_RE.match(n):
                season_dirs.append(n)
            continue
        dir_file_count += 1
        q = parse_media_name(n)
        (media if q.is_media else companions).append((e, q))

    season_file_count = 0
    for sd in season_dirs:
        try:
            for e in a.client.list_all(f"{w.rstrip('/')}/{sd}", refresh=False):
                if e.get("is_dir"):
                    continue
                season_file_count += 1
                q = parse_media_name(e.get("name") or "")
                if q.is_media:
                    media.append((e, q))
        except Exception:
            pass

    # 目录期望名（仅作参考；「是否合规」一律以审计器结论为准，见下）
    v = eng.build_vars(title=p.title or folder, year=p.year or "", tmdb_id=tmdb_id)
    expected_folder = eng.folder_name(v, kind)

    # 主文件（电影取体积最大）与版本信息
    main_name, main_tech, total_size = "", "", 0
    stems, res_list, tech_list = [], [], []
    if media:
        biggest, biggest_size = None, -1
        for e, q in media:
            sz = e.get("size") or 0
            total_size += sz
            if sz >= biggest_size:
                biggest, biggest_size = (e, q), sz
        main_name = biggest[0].get("name") or ""
        main_tech = biggest[1].tech
        stems = spec.media_stems([e.get("name") or "" for e, _q in media])
        for _e, q in media:
            if q.resolution and q.resolution not in res_list:
                res_list.append(q.resolution)
            if q.tech and q.tech not in tech_list:
                tech_list.append(q.tech)
    multi_version = spec.count_versions(stems) > 1
    resolution = " + ".join(res_list)

    img_names = [e.get("name") or "" for e, _q in companions
                 if (e.get("name") or "").rsplit(".", 1)[-1].lower() in
                 {x.lstrip(".") for x in __import__("aix8pan.core.parser", fromlist=["IMAGE_EXTS"]).IMAGE_EXTS}]
    nfo_names = [e.get("name") or "" for e, _q in companions
                 if (e.get("name") or "").lower().endswith(".nfo")]
    sub_names = [e.get("name") or "" for e, _q in companions
                 if (e.get("name") or "").lower().endswith(".srt")]

    issues = a._audit_work(w, kind)
    errs = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    infos = [i for i in issues if i["level"] == "info"]

    def codes(pref: str) -> list[str]:
        return [i["code"] for i in issues if i["code"].startswith(pref)]

    file_bad = codes("FILE_") + codes("NO_MEDIA")
    art_bad = codes("ART_") + codes("NFO_")
    folder_bad = codes("FOLDER_")
    folder_ok = not folder_bad
    # 目录已合规时，「规范目录名（应为）」就等于现状；否则给出建议名。
    # 注意不能用 `folder == expected_folder` 自查 —— expected_folder 由
    # parse_media_name 的标题渲染，而它会把全角括号「（上）」清洗成空格，
    # 导致 `哈利·波特与死亡圣器（上）` 这类合法名被误判（历史踩坑）。
    if folder_ok:
        expected_folder = folder

    return {
        "category": cat,
        "container": rel_container(w, root),
        "path": w,
        "folder_raw": folder,
        "title": p.title or "",
        "year": p.year or "",
        "tmdb_id": tmdb_id,
        "id_tag_raw": id_tag_raw,
        "id_legacy": bool(m and m.group(1).lower() != "tmdbid"),
        "kind": kind,
        "expected_folder": expected_folder,
        "folder_ok": folder_ok,
        "folder_issues": folder_bad,
        "media_count": len(media),
        "files_total": dir_file_count + season_file_count,
        "files_other": (dir_file_count + season_file_count) - len(media),
        "version_count": spec.count_versions(stems),
        "multi_version": multi_version,
        "season_dirs": season_dirs,
        "main_file": main_name,
        "tech": main_tech,
        "resolution": resolution,
        "tech_all": " / ".join(tech_list),
        "size_mb": round(total_size / 1048576, 1),
        "images": img_names,
        "nfos": nfo_names,
        "subs": sub_names,
        "file_ok": not file_bad,
        "file_issues": file_bad,
        "art_ok": not art_bad,
        "art_issues": art_bad,
        "errors": [i["detail"] for i in errs],
        "warns": [i["detail"] for i in warns],
        "infos": [i["detail"] for i in infos],
        "issues": issues,          # 完整 [{code,level,detail,suggestion}]
        "n_err": len(errs),
        "n_warn": len(warns),
        "n_info": len(infos),
        "conform": (len(errs) == 0 and len(warns) == 0),
        "info_only": (len(errs) == 0 and len(warns) == 0 and len(infos) > 0),
    }


def write_out(rows: list[dict]) -> None:
    out = {
        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(rows),
        "conform": sum(1 for r in rows if r["conform"]),
        "rows": rows,
    }
    DEST.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {DEST}  total={len(rows)} conform={out['conform']}")


def parse_args(argv: list[str]) -> tuple[str, list[str], list[str]]:
    """返回 (分类过滤, sync 路径列表, drop 路径列表)。"""
    only, sync, drop = "", [], []
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
        elif not argv[i].startswith("--"):
            only = argv[i]
            i += 1
        else:
            i += 1
    return only, sync, drop


def main() -> int:
    only, sync, drop = parse_args(sys.argv[1:])
    a = Auditor()
    eng = NamingEngine(a.cfg.get("naming") or {})

    # ── 增量模式 ──────────────────────────────────────────
    if sync or drop:
        if not DEST.exists():
            print("❌ 增量模式要求已有全量缓存 data/state/container_scan.json（先跑一次全量）")
            return 2
        old = json.loads(DEST.read_text(encoding="utf-8"))["rows"]
        stale = set(sync) | set(drop)
        rows = [r for r in old if r["path"] not in stale]
        print(f"缓存 {len(old)} 行 → 移除 {len(old) - len(rows)} 行（sync+drop）")
        for w in sync:
            rc = root_of(w)
            if not rc:
                print(f"  ⚠ 路径不在 合集/专辑 下，跳过: {w}")
                continue
            root, cat = rc
            try:
                row = scan_work(a, eng, w, root, cat)
            except Exception as e:  # noqa: BLE001
                print(f"  ❌ 扫描失败 {w}: {e}")
                continue
            rows.append(row)
            print(f"  ✔ {row['category']}/{row['container']}/{row['folder_raw']}"
                  f"  conform={row['conform']}")
        write_out(rows)
        return 0

    # ── 全量模式 ──────────────────────────────────────────
    rows: list[dict] = []
    for root, cat in ROOTS:
        if only and only != cat:
            continue
        print(f"--- scanning {root}", file=sys.stderr, flush=True)
        works = a._find_works(root, include_containers=True, max_depth=6)
        print(f"    found {len(works)} works", file=sys.stderr, flush=True)

        for i, w in enumerate(works, 1):
            rows.append(scan_work(a, eng, w, root, cat))
            if i % 10 == 0:
                print(f"    {i}/{len(works)}", file=sys.stderr, flush=True)

    write_out(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
