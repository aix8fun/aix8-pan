#!/usr/bin/env python3
"""三国演义 (1994) 剧集整理：
1. Season 1 → Season 01
2. 84 集场景命名 → 「三国演义 - S01E01 - 桃园三结义 [2160p WEB-DL H265 AAC].mp4」
3. 补刮 clearlogo.png（TMDB tv-72645 有 4 个 logo）
4. 校验 tvshow.nfo 的 tmdbid 是否为 72645

用法：
    --dry-run   只打印计划
    --execute   限速执行
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aix8pan.core.openlist import OpenListClient
from aix8pan.core.tmdb import TMDBClient
from aix8pan.config import load_config

BASE = "/115/02-剧集/三国演义 (1994)"
TV_ID = "72645"
PAUSE_OP = 1.6
PAUSE_EVERY = 40
PAUSE_S = 20

# 场景名 → 规范技术标签：2160p.WEB-DL.HQ.H265.AAC-HiveWeb → [2160p WEB-DL H265 AAC]
DROP_TAGS = {"HQ", "HIVEWEB", "10BIT", "8BIT"}


def tech_bracket(scene: str) -> str:
    """从场景名提取技术标签并规范成 […]。"""
    m = re.search(r"(2160p|1080p|720p|480p)[.\s]*(.*)$", scene, re.I)
    if not m:
        return ""
    tokens = re.split(r"[.\s]+", m.group(1) + "." + m.group(2))
    keep = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        # 「AAC-HiveWeb」这类 标签-发布组：去掉发布组，保留前面已知标签
        if "-" in t and t.upper() != "WEB-DL":
            t = t.split("-")[0]
        up = t.upper()
        if up in DROP_TAGS or re.match(r"^\d{4}$", t):
            continue
        if up == "H265":
            t = "H265"
        elif up == "WEB-DL":
            t = "WEB-DL"
        keep.append(t)
    return "[" + " ".join(keep) + "]" if keep else ""


def main() -> int:
    dry = "--execute" not in sys.argv
    cfg = load_config()
    ocfg = json.loads(Path("config.json").read_text(encoding="utf-8"))["openlist"]
    c = OpenListClient(ocfg["base_url"], ocfg["username"], ocfg["password"], ocfg["op_interval_ms"])
    t = cfg["tmdb"]
    tmdb = TMDBClient(t["api_key"], t["api_host"], t["image_host"], t["language"],
                      t["request_interval_ms"])

    # ── 1. 拉全部单集标题（一次 season 接口） ────────────────
    sd = tmdb._get(f"/tv/{TV_ID}/season/1", {"language": tmdb.language})
    ep_titles = {e["episode_number"]: e.get("name") or "" for e in sd.get("episodes") or []}
    print(f"TMDB S1 单集标题 {len(ep_titles)} 个")

    # ── 2. 生成改名计划 ──────────────────────────────────
    season_dir_old = BASE + "/Season 1"
    season_dir_new = BASE + "/Season 01"
    files = [e["name"] for e in c.list_all(season_dir_old, refresh=True) if not e.get("is_dir")]
    plans = []  # (old_name, new_name)
    for fn in files:
        m = re.match(r".*?S01E(\d{2})\.(.*)\.mp4$", fn, re.I)
        if not m:
            print(f"  ⚠️ 无法解析: {fn}")
            continue
        ep = int(m.group(1))
        title = ep_titles.get(ep, f"第{ep}集").replace("/", "／")
        bracket = tech_bracket(m.group(2))
        new = f"三国演义 - S01E{ep:02d} - {title}" + (f" {bracket}" if bracket else "") + ".mp4"
        plans.append((fn, new))
    # 碰撞检查
    targets = [n for _, n in plans]
    assert len(set(targets)) == len(targets), "目标名有重复！"
    print(f"改名计划 {len(plans)} 个，无碰撞")
    for old, new in plans[:5]:
        print(f"  {old[:60]} → {new}")
    print("  …")

    if dry:
        print("\nDRY-RUN 完成，加 --execute 执行")
        return 0

    # ── 3. 执行：季目录改名 ────────────────────────────────
    step = 0
    c.rename(season_dir_old, "Season 01")
    step += 1
    print(f"[{step:>3}] Season 1 → Season 01 ✅")
    time.sleep(PAUSE_OP)

    # ── 4. 执行：84 集改名 ────────────────────────────────
    fails = []
    for old, new in plans:
        step += 1
        try:
            c.rename(f"{season_dir_new}/{old}", new)
            if step % 10 == 0:
                print(f"[{step:>3}] {old[:50]} → {new[:60]} ✅")
        except Exception as e:  # noqa: BLE001
            fails.append((old, str(e)))
            print(f"[{step:>3}] ❌ {old}: {e}")
        time.sleep(PAUSE_OP)
        if step % PAUSE_EVERY == 0:
            print(f"  …休息 {PAUSE_S}s")
            time.sleep(PAUSE_S)

    # ── 5. 补刮 clearlogo.png ─────────────────────────────
    step += 1
    try:
        imgs = (tmdb.detail(TV_ID, "tv").get("images") or {}).get("logos") or []
        zh = [l for l in imgs if l.get("iso_639_1") in ("zh", "cn")]
        en = [l for l in imgs if l.get("iso_639_1") == "en"]
        pick = sorted(zh or en or imgs, key=lambda x: -(x.get("vote_average") or 0))[0]
        data = tmdb.download_image(pick["file_path"])
        c.upload(BASE + "/clearlogo.png", data, overwrite=True)
        print(f"[{step:>3}] clearlogo.png ✅ ({pick.get('iso_639_1')}, {pick.get('width')}x{pick.get('height')})")
    except Exception as e:  # noqa: BLE001
        print(f"[{step:>3}] ⚠️ clearlogo 失败: {e}")

    # ── 6. 校验 tvshow.nfo ────────────────────────────────
    step += 1
    try:
        import requests
        info = c.get_info(BASE + "/tvshow.nfo")
        url = info.get("raw_url") or ""
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                    "Chrome/126.0 Safari/537.36"}, timeout=30)
        txt = r.content.decode("utf-8", "replace") if r.status_code == 200 else ""
        has_id = "72645" in txt
        print(f"[{step:>3}] tvshow.nfo {'含 tmdbid 72645 ✅' if has_id else '不含 72645 ⚠️ 需重生成'}"
              f" (HTTP {r.status_code}, {len(txt)}B)")
        if txt and not has_id:
            print("  --- nfo 内容前 400 字 ---")
            print(txt[:400])
    except Exception as e:  # noqa: BLE001
        print(f"[{step:>3}] ⚠️ nfo 校验失败: {e}")

    print(f"\n完成：{step - len(fails)}/{step} 步成功，失败 {len(fails)}")
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
