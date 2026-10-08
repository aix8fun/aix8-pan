#!/usr/bin/env python3
"""整理 01-电影根目录 3 个散件：建规范目录 → 移入 → B1 改名 → 刮削 → 归位。

用法:
    python scripts/archive/fix_strays3.py --dry-run
    python scripts/archive/fix_strays3.py --execute

三部均归属既有系列容器（TMDB 已确认）:
    惊天魔盗团3 (425274)        → 合集/惊天魔盗团（系列）    [.iso 原盘]
    疯狂动物城 (269149)         → 合集/疯狂动物城（系列）
    侏罗纪世界：重生 (1234821)  → 合集/侏罗纪公园（系列）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aix8pan.openlist import OpenListClient  # noqa: E402
from aix8pan.scraper import Scraper  # noqa: E402

ROOT = "/115/01-电影"
OP_SLEEP = 1.6

WORKS = [
    {
        "src": "[惊天魔盗团3 2025][4K 美版原盘 DIY简繁粤 双语字幕][Dolby Vision|HDR10 Atmos 7.1][Thor@HDSky][82.48G].iso",
        "dir": "惊天魔盗团3 (2025) {tmdbid-425274}",
        "stem": "惊天魔盗团3 Now You See Me - Now You Don't (2025) [2160p DV HDR10 TrueHD Atmos]",
        "ext": "iso",
        "tmdb": "425274",
        "target": ROOT + "/合集/惊天魔盗团（系列）",
    },
    {
        "src": "Zootopia.2016.2160p.BluRay.REMUX.HEVC.TrueHD.7.1.Atmos-FGT.mkv",
        "dir": "疯狂动物城 (2016) {tmdbid-269149}",
        "stem": "疯狂动物城 Zootopia (2016) [2160p TrueHD Atmos]",
        "ext": "mkv",
        "tmdb": "269149",
        "target": ROOT + "/合集/疯狂动物城（系列）",
    },
    {
        "src": "侏罗纪世界：重生.Jurassic.World.Rebirth.2025.iTunes.WEB-DL.2160p.DV.HDR.DDP.5.1.Atmos.1Audios-LGNB@oSpecialCN.mkv",
        "dir": "侏罗纪世界：重生 (2025) {tmdbid-1234821}",
        "stem": "侏罗纪世界：重生 Jurassic World Rebirth (2025) [2160p DV HDR DDP5.1 Atmos]",
        "ext": "mkv",
        "tmdb": "1234821",
        "target": ROOT + "/合集/侏罗纪公园（系列）",
    },
]


def main() -> int:
    execute = "--execute" in sys.argv
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json")
                     .read_text(encoding="utf-8"))["openlist"]
    client = OpenListClient(cfg["base_url"], cfg["username"], cfg["password"],
                            op_interval_ms=cfg["op_interval_ms"])
    scraper = Scraper(client=client)

    print(f"== {'执行' if execute else 'DRY-RUN'} ==", flush=True)
    n_ok = n_fail = 0

    for w in WORKS:
        work_dir = f"{w['target']}/{w['dir']}"
        new_name = f"{w['stem']}.{w['ext']}"
        print(f"\n■ {w['src'][:60]}… → {w['target'].replace(ROOT + '/', '')}/{w['dir']}/",
              flush=True)
        print(f"   mkdir      {work_dir}", flush=True)
        print(f"   move       {w['src'][:50]}…  → 作品目录", flush=True)
        print(f"   rename     → {new_name}", flush=True)
        print("   scrape     poster/fanart/clearlogo/nfo", flush=True)
        if not execute:
            continue

        try:
            names = {e["name"] for e in client.list_all(ROOT, refresh=True)}
            if w["src"] not in names:
                print("   ⚠ 源文件不在根目录，跳过（可能已处理）", flush=True)
                continue
            client.ensure_dir(work_dir)
            time.sleep(OP_SLEEP)
            client.move(ROOT, [w["src"]], work_dir)
            time.sleep(OP_SLEEP)
            client.rename(f"{work_dir}/{w['src']}", new_name)
            time.sleep(OP_SLEEP)
            r = scraper.scrape(work_dir, media_type="movie", tmdb_id=w["tmdb"])
            if not r.get("ok"):
                raise RuntimeError(r.get("error"))
            print(f"   ✔ scrape 上传: {', '.join(r.get('uploaded', [])) or '无'}",
                  flush=True)
            n_ok += 1
            time.sleep(OP_SLEEP)

            final = {e["name"] for e in client.list_all(work_dir, refresh=True)}
            stem = w["stem"]
            want = {f"{stem}.{w['ext']}", f"{stem}-poster.jpg",
                    f"{stem}-fanart.jpg", f"{stem}-clearlogo.png", f"{stem}.nfo"}
            missing = want - final
            if missing:
                print(f"   ⚠ 回读缺: {missing}", flush=True)
                n_fail += 1
            else:
                print(f"   ✅ 回读验证通过（{len(final)} 个文件）", flush=True)
        except Exception as e:  # noqa: BLE001
            n_fail += 1
            print(f"   ❌ {e}", flush=True)
            time.sleep(OP_SLEEP * 2)

    print(f"\n== 完成: 成功 {n_ok} 部, 失败 {n_fail} 部 ==", flush=True)
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
