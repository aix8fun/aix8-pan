#!/usr/bin/env python3
"""整理 0-待整理 的 9 部作品：规范命名 → 刮削 → 归位到 合集/专辑。

用法:
    python scripts/archive/fix_strays2.py --dry-run    # 只打印计划
    python scripts/archive/fix_strays2.py --execute    # 执行（限速防风控）

归位方案（TMDB 已确认）:
    唐探1900 (1357305)     → 合集/唐人街探案（系列）   [已规范，仅移动]
    蛟龙行动 (1280330)     → 合集/红海行动（系列）     [改名+刮削+移动]
    疯狂动物城2 (1084242)  → 合集/疯狂动物城（系列）   [新建合集目录]
    其余 6 部              → 专辑/
    （长安的荔枝、戏台已规范，仅移动；南京照相馆/落叶归根/浪浪山小妖怪/镖人 改名+刮削+移动）

每部操作:
    1. 主文件改为 B1 规范名（国产片标题双写；疯狂动物城2 用 中+英）
    2. 既有 poster/fanart/nfo 先改名前缀化（保住现有素材），再 scrape 补缺
       （clearlogo / nfo 等，已存在的一律跳过，绝不覆盖）
    3. 目录 {tmdb-} → {tmdbid-}（仅落叶归根）
    4. 移动到目标容器（需要时先 mkdir）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aix8pan.core.openlist import OpenListClient  # noqa: E402
from aix8pan.pipeline.scraper import Scraper  # noqa: E402

ROOT = "/115/01-电影"
SRC = ROOT + "/0-待整理"
OP_SLEEP = 1.6          # 每次写操作间隔（防风控）

# mode: move_only | full（改名+刮削+移动）
WORKS = [
    # --- 已规范，仅归位 ---
    {"folder": "长安的荔枝 (2025) {tmdbid-1356587}", "tmdb": "1356587",
     "mode": "move_only", "target": ROOT + "/专辑"},
    {"folder": "戏台 (2025) {tmdbid-1406607}", "tmdb": "1406607",
     "mode": "move_only", "target": ROOT + "/专辑"},
    {"folder": "唐探1900 (2025) {tmdbid-1357305}", "tmdb": "1357305",
     "mode": "move_only", "target": ROOT + "/合集/唐人街探案（系列）"},
    # --- 需改名 + 刮削 + 归位 ---
    {"folder": "南京照相馆 (2025) {tmdbid-1500536}", "tmdb": "1500536",
     "mode": "full",
     "main": "南京照相馆.Dead.To.Rights.2025.2160p.HQ.WEB-DL.H265.DV.DTS-QuickIO.mkv",
     "stem": "南京照相馆 南京照相馆 (2025) [2160p DV DTS]",
     "renames": [],
     "target": ROOT + "/专辑"},
    {"folder": "浪浪山小妖怪 (2025) {tmdbid-1304434}", "tmdb": "1304434",
     "mode": "full",
     "main": "Nobody.2025.2160p.WEB-DL.HDR.Vivid.H.265.DDP5.1-HiveWeb.mp4",
     "stem": "浪浪山小妖怪 浪浪山小妖怪 (2025) [2160p HDR DDP5.1]",
     "renames": [],
     "target": ROOT + "/专辑"},
    {"folder": "蛟龙行动 (2025) {tmdbid-1280330}", "tmdb": "1280330",
     "mode": "full",
     "main": "蛟龙行动.Operation.Leviathan.2025.2160p.HQ.WEB-DL.H265.HDR.DTS-QuickIO.mkv",
     "stem": "蛟龙行动 蛟龙行动 (2025) [2160p HDR DTS]",
     "renames": [],
     "target": ROOT + "/合集/红海行动（系列）"},
    {"folder": "疯狂动物城2 (2025) {tmdbid-1084242}", "tmdb": "1084242",
     "mode": "full",
     "main": "疯狂动物城2.Zootopia.2.2025.2160p.HEVC.H.265.HDR10.PCM5.1_2026.01.08-02.57.07.mkv",
     "stem": "疯狂动物城2 Zootopia 2 (2025) [2160p HDR10 PCM5.1]",
     "renames": [],
     "target": ROOT + "/合集/疯狂动物城（系列）"},
    {"folder": "镖人：风起大漠 (2026) {tmdbid-1305781}", "tmdb": "1305781",
     "mode": "full",
     "main": "镖人：风起大漠 (2026) [2160p.Ultra HD BluRay.Remux.DV.HDR10.H.265.10-bit.24fps.TrueHD Dolby Atmos 7.1-XH].mkv",
     "stem": "镖人：风起大漠 镖人：风起大漠 (2026) [2160p DV HDR10 TrueHD Atmos]",
     "renames": [],
     "target": ROOT + "/专辑"},
    {"folder": "落叶归根 (2007) {tmdb-36113}", "tmdb": "36113",
     "mode": "full",
     "main": "落叶归根 (2007) [2160p h265 EAC3].mkv",
     "stem": "落叶归根 落叶归根 (2007) [2160p h265 EAC3]",
     # 既有素材先前缀化（保住现有海报/富 nfo），scrape 只补 clearlogo
     "renames": [("落叶归根 (2007) [2160p h265 EAC3].nfo", "{stem}.nfo"),
                 ("poster.jpg", "{stem}-poster.jpg"),
                 ("fanart.jpg", "{stem}-fanart.jpg")],
     "folder_new": "落叶归根 (2007) {tmdbid-36113}",
     "target": ROOT + "/专辑"},
]


def main() -> int:
    execute = "--execute" in sys.argv
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json")
                     .read_text(encoding="utf-8"))["openlist"]
    client = OpenListClient(cfg["base_url"], cfg["username"], cfg["password"],
                            op_interval_ms=cfg["op_interval_ms"])
    scraper = Scraper(client=client)

    mode = "执行" if execute else "DRY-RUN"
    print(f"== {mode} ==", flush=True)
    made_dirs: set[str] = set()
    n_ok = n_fail = 0

    for w in WORKS:
        folder = w["folder"]
        cur_dir = f"{SRC}/{folder}"
        target = w["target"]
        print(f"\n■ {folder} → {target.replace(ROOT + '/', '')}/", flush=True)

        steps: list[tuple[str, str, str]] = []
        if w["mode"] == "full":
            ext = w["main"].rsplit(".", 1)[-1]
            steps.append(("rename", w["main"], f"{w['stem']}.{ext}"))
            for src, dst in w["renames"]:
                steps.append(("rename", src, dst.replace("{stem}", w["stem"])))
            steps.append(("scrape", "", ""))
            if w.get("folder_new"):
                steps.append(("rename_dir", folder, w["folder_new"]))
        steps.append(("move", w.get("folder_new", folder), target))

        for op, src, dst in steps:
            print(f"   {op:10s} {src}" + (f"  →  {dst}" if dst else ""), flush=True)
        if not execute:
            continue

        # 执行
        try:
            names = {e["name"] for e in client.list_all(cur_dir, refresh=True)}
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ 目录读取失败，跳过: {e}", flush=True)
            n_fail += 1
            continue

        for op, src, dst in steps:
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
                    print(f"   ✔ rename {src}", flush=True)
                elif op == "scrape":
                    r = scraper.scrape(cur_dir, media_type="movie",
                                       tmdb_id=w["tmdb"], cleanup_legacy=True)
                    if not r.get("ok"):
                        raise RuntimeError(r.get("error"))
                    print(f"   ✔ scrape 上传 {len(r.get('uploaded', []))} 个: "
                          f"{', '.join(r.get('uploaded', [])) or '无（均已存在）'}",
                          flush=True)
                elif op == "rename_dir":
                    client.rename(cur_dir, dst)
                    cur_dir = f"{SRC}/{dst}"
                    folder = dst
                    print(f"   ✔ rename_dir → {dst}", flush=True)
                elif op == "move":
                    if target not in made_dirs:
                        client.ensure_dir(target)
                        made_dirs.add(target)
                        time.sleep(OP_SLEEP)
                    client.move(SRC, [folder], target)
                    print(f"   ✔ move → {target}/", flush=True)
                n_ok += 1
                time.sleep(OP_SLEEP)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                print(f"   ❌ {op} {src}: {e}", flush=True)
                time.sleep(OP_SLEEP * 2)

        # 回读验证
        try:
            final_dir = f"{target}/{folder}"
            final = {e["name"] for e in client.list_all(final_dir, refresh=True)}
            if w["mode"] == "full":
                stem = w["stem"]
                ext = w["main"].rsplit(".", 1)[-1]
                want = {f"{stem}.{ext}", f"{stem}-poster.jpg",
                        f"{stem}-fanart.jpg", f"{stem}-clearlogo.png",
                        f"{stem}.nfo"}
                missing = want - final
                legacy = {x for x in final
                          if x in ("poster.jpg", "fanart.jpg", "logo.png",
                                   "movie.nfo", "backdrop.jpg")}
                if missing or legacy:
                    print(f"   ⚠ 回读异常: 缺 {missing or '无'} / 残留 {legacy or '无'}",
                          flush=True)
                    n_fail += 1
                else:
                    print(f"   ✅ 回读验证通过（{len(final)} 个文件）", flush=True)
            else:
                print(f"   ✅ 已归位（{len(final)} 个文件）", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ 回读失败: {e}", flush=True)
            n_fail += 1

    print(f"\n== 完成: 成功 {n_ok} 步, 失败 {n_fail} 步 ==", flush=True)
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
