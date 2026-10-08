#!/usr/bin/env python3
"""通用剧集整理脚本（v2.2 规范）：

对 02-剧集 下某部作品执行：
  1. 季目录 Season N → Season 0N（两位补零）
  2. 单集改名 → 「{标题} - SxxExx - {真实集名} [技术标签].{ext}」
     （真实集名来自 TMDB season 接口；技术标签从原文件名提取规范成方括号，
       原文件名无技术信息则不带括号）
  3. 补刮缺失的 seasonNN-poster.jpg / clearlogo.png
  4. 校验 tvshow.nfo 的 tmdbid
  5. 根目录改名 → {标题} ({年份}) {tmdbid-N}（最后做）

用法：
    python scripts/fix_tv_one.py --dir "白夜追凶 (2017)" [--tv-id 73982] --dry-run
    python scripts/fix_tv_one.py --dir "白夜追凶 (2017)" [--tv-id 73982] --execute
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.openlist import OpenListClient
from aix8pan.tmdb import TMDBClient
from aix8pan.config import load_config

TV_ROOT = "/115/02-剧集"
PAUSE_OP = 1.6
PAUSE_EVERY = 40
PAUSE_S = 20

DROP_TAGS = {"HQ", "HIVEWEB", "10BIT", "8BIT"}
SE_RE = re.compile(r"[SＳ](\d{1,2})[EＥ](\d{1,3})", re.I)
FOLDER_RE = re.compile(r"^(.*?)\s*\((\d{4})\)\s*(\{tmdbid-\d+\})?$")


def tech_bracket(name: str) -> str:
    """从文件名提取技术标签并规范成 […]；无技术信息返回 ''。"""
    m = re.search(r"(2160p|1080p|720p|480p|4K)[.\s]*(.*)$", name, re.I)
    if not m:
        return ""
    tokens = re.split(r"[.\s]+", m.group(1) + "." + m.group(2))
    keep = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if "-" in t and t.upper() != "WEB-DL":
            t = t.split("-")[0]
        up = t.upper()
        if up in DROP_TAGS or re.match(r"^\d{4}$", t):
            continue
        keep.append({"H265": "H265", "H264": "H264", "WEB-DL": "WEB-DL"}.get(up, t))
    return "[" + " ".join(keep) + "]" if keep else ""


def sanitize(title: str) -> str:
    return title.replace("/", "／").replace("\\", "＼").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="02-剧集 下的作品目录名")
    ap.add_argument("--tv-id", default="", help="TMDB tv id（可跳过搜索）")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    dry = not args.execute

    cfg = load_config()
    ocfg = json.loads(Path("config.json").read_text(encoding="utf-8"))["openlist"]
    c = OpenListClient(ocfg["base_url"], ocfg["username"], ocfg["password"], ocfg["op_interval_ms"])
    t = cfg["tmdb"]
    tmdb = TMDBClient(t["api_key"], t["api_host"], t["image_host"], t["language"],
                      t["request_interval_ms"])

    m = FOLDER_RE.match(args.dir)
    assert m, f"目录名无法解析: {args.dir}"
    title, year, old_tag = m.group(1).strip(), m.group(2), m.group(3)

    # ── TMDB 匹配 ─────────────────────────────────────────
    tv_id = args.tv_id
    if not tv_id:
        res = tmdb.search(title, year, "tv")
        cands = res.get("tv") or []
        assert cands, f"TMDB 搜不到: {title} {year}"
        tv_id = str(cands[0]["id"])
        print(f"TMDB 匹配: {tv_id} {cands[0].get('name')} ({(cands[0].get('first_air_date') or '')[:4]})")
    d = tmdb.detail(tv_id, "tv")
    tmdb_title = d.get("name") or title

    base = f"{TV_ROOT}/{args.dir}"
    new_base = f"{TV_ROOT}/{tmdb_title} ({year}) {{tmdbid-{tv_id}}}"

    # ── 收集季目录与改名计划 ──────────────────────────────
    entries = c.list_all(base, refresh=True)
    season_dirs = [e["name"] for e in entries if e.get("is_dir")
                   and re.match(r"^Season\s*\d+$", e["name"], re.I)]
    plans = []          # (season_no, old_path_dir, old_name, new_name)
    season_renames = [] # (old_dir_name, new_dir_name)
    ep_title_cache: dict[int, dict[int, str]] = {}

    for sd in sorted(season_dirs):
        sn = int(re.search(r"(\d+)", sd).group(1))
        if sd != f"Season {sn:02d}":
            season_renames.append((sd, f"Season {sn:02d}"))
        if sn not in ep_title_cache:
            data = tmdb._get(f"/tv/{tv_id}/season/{sn}", {"language": tmdb.language})
            ep_title_cache[sn] = {e["episode_number"]: sanitize(e.get("name") or "")
                                  for e in data.get("episodes") or []}
        for f in c.list_all(f"{base}/{sd}", refresh=True):
            if f.get("is_dir"):
                continue
            fn = f["name"]
            se = SE_RE.search(fn)
            if not se:
                print(f"  ⚠️ 无法解析季集号: {fn}")
                continue
            s_no, e_no = int(se.group(1)), int(se.group(2))
            ext = fn.rsplit(".", 1)[-1].lower()
            ep_title = ep_title_cache.get(sn, {}).get(e_no) or f"第{e_no}集"
            bracket = tech_bracket(fn)
            new = (f"{tmdb_title} - S{s_no:02d}E{e_no:02d} - {ep_title}"
                   + (f" {bracket}" if bracket else "") + f".{ext}")
            if fn != new:
                plans.append((sn, sd, fn, new))

    targets = [(sn, n) for sn, _, _, n in plans]
    assert len(set(targets)) == len(targets), "目标名有重复！"

    # ── artwork 补齐计划 ─────────────────────────────────
    root_files = {e["name"] for e in entries if not e.get("is_dir")}
    tmdb_imgs = d.get("images") or {}
    art_jobs = []  # (kind, remote_name, image_path)
    for s in (d.get("seasons") or []):
        sn = s.get("season_number") or 0
        if sn >= 1 and s.get("poster_path"):
            nm = f"season{sn:02d}-poster.jpg"
            if nm not in root_files:
                art_jobs.append(("season-poster", nm, s["poster_path"]))
    if "clearlogo.png" not in root_files:
        logos = tmdb_imgs.get("logos") or []
        if logos:
            zh = [l for l in logos if l.get("iso_639_1") in ("zh", "cn")]
            en = [l for l in logos if l.get("iso_639_1") == "en"]
            pick = sorted(zh or en or logos, key=lambda x: -(x.get("vote_average") or 0))[0]
            art_jobs.append(("clearlogo", "clearlogo.png", pick["file_path"]))
        else:
            print("  ℹ️ TMDB 无 logo，clearlogo 跳过")

    # ── 汇总计划 ─────────────────────────────────────────
    print(f"\n== 计划 ==  {args.dir} → {new_base.split('/')[-1]}")
    print(f"  季目录改名: {len(season_renames)}  {season_renames}")
    print(f"  单集改名: {len(plans)}")
    for sn, sd, old, new in plans[:4]:
        print(f"    {old[:55]} → {new[:70]}")
    if len(plans) > 4:
        print(f"    … 共 {len(plans)} 个")
    print(f"  补刮 artwork: {[n for _, n, _ in art_jobs]}")
    if dry:
        print("\nDRY-RUN 完成，加 --execute 执行")
        return 0

    # ── 执行 ─────────────────────────────────────────────
    step, fails = 0, []

    def tick():
        nonlocal step
        step += 1
        time.sleep(PAUSE_OP)
        if step % PAUSE_EVERY == 0:
            print(f"  …休息 {PAUSE_S}s")
            time.sleep(PAUSE_S)

    # 1) 单集改名（在旧季目录名下进行）
    for sn, sd, old, new in plans:
        try:
            c.rename(f"{base}/{sd}/{old}", new)
        except Exception as e:  # noqa: BLE001
            fails.append((old, str(e)))
            print(f"  ❌ {old}: {e}")
        tick()
        if step % 20 == 0:
            print(f"  [{step:>3}] 已改 {step} 个…")
    print(f"单集改名完成 {len(plans) - len(fails)}/{len(plans)}")

    # 2) 季目录改名
    for old, new in season_renames:
        try:
            c.rename(f"{base}/{old}", new)
            print(f"  {old} → {new} ✅")
        except Exception as e:  # noqa: BLE001
            fails.append((old, str(e)))
            print(f"  ❌ 季目录 {old}: {e}")
        tick()

    # 3) 补刮 artwork
    for kind, nm, path in art_jobs:
        try:
            data = tmdb.download_image(path)
            c.upload(f"{base}/{nm}", data, overwrite=True)
            print(f"  {nm} ✅")
        except Exception as e:  # noqa: BLE001
            fails.append((nm, str(e)))
            print(f"  ❌ {nm}: {e}")
        tick()

    # 4) 根目录改名（最后）
    if not old_tag:
        try:
            c.rename(base, new_base.split("/")[-1])
            print(f"  根目录 → {new_base.split('/')[-1]} ✅")
            base = new_base
        except Exception as e:  # noqa: BLE001
            fails.append((args.dir, str(e)))
            print(f"  ❌ 根目录: {e}")
        tick()

    # 5) 校验 tvshow.nfo
    try:
        import requests
        info = c.get_info(f"{base}/tvshow.nfo")
        sign = info.get("sign") or ""
        from urllib.parse import quote
        url = (ocfg["base_url"].rstrip("/") + "/d"
               + quote(f"{base}/tvshow.nfo") + f"?sign={sign}")
        r = requests.get(url, timeout=30)
        txt = r.content.decode("utf-8", "replace") if r.status_code == 200 else ""
        ok = tv_id in txt
        print(f"  tvshow.nfo tmdbid {tv_id}: {'✅' if ok else '⚠️ 缺失需重生成'}"
              f" (HTTP {r.status_code})")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ nfo 校验失败: {e}")

    print(f"\n完成：失败 {len(fails)} / 总步 {step}")
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
