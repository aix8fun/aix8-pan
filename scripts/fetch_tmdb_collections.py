#!/usr/bin/env python
"""抓取「合集 / 专辑」每部作品的 TMDB 归属合集，以及每个合集的成员名单。

产出 data/state/tmdb_collections.json：
    {
      "generated_at": ...,
      "today": "2026-10-07",
      "by_movie": { "<tmdb_movie_id>": {"collection_id": 645, "collection_name": "007（系列）"} },
      "series":   { "<container>": {"collection_id": 645, "votes": {...}, "mixed": false} },
      "collections": { "645": {"id","name_zh","name_en","original_name","slug","url",
                               "count_total","count_released","count_unreleased",
                               "parts":[{"id","title","release_date","released"}]} }
    }

限速：TMDB 走配置里的 request_interval_ms；官网 canonical URL 解析另有 0.4s 间隔。
只读，不碰网盘、不写 TMDB。

增量模式:
    python scripts/fetch_tmdb_collections.py --incremental
        复用 data/state/tmdb_collections.json 缓存：by_movie 只查缓存里没有（或之前
        失败）的 tmdb_id；collections 只补新出现的合集；已缓存合集的
        「是否已上映」按今天日期就地重算（不调 API）。
        不再被 scan 引用的电影/系列/合集会被自动剔除。
    追加 --refresh-collections 可强制重取全部合集详情（成员变动时）。
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.paths import state_path

from aix8pan.config import load_config          # noqa: E402
from aix8pan.tmdb import TMDBClient             # noqa: E402

SCAN = state_path("container_scan.json")
OUT = state_path("tmdb_collections.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
WEB = "https://www.themoviedb.org"
SLUG_SLEEP = 0.4


def slugify(name: str) -> str:
    """复刻 TMDB 官网 slug 规则：小写、去非 [a-z0-9 -]、空格→连字符。"""
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s.strip())
    return re.sub(r"-{2,}", "-", s).strip("-") or "collection"


class _Redirect(Exception):
    def __init__(self, url: str):
        self.url = url


class _Capture(urllib.request.HTTPRedirectHandler):
    """拦截首跳重定向，避免把整页 HTML 拉下来。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise _Redirect(newurl)


def canonical_url(collection_id: int, fallback_slug: str) -> tuple[str, str]:
    """返回 (url, 来源)。跟随 themoviedb.org 的首跳重定向拿官方 slug。"""
    req = urllib.request.Request(
        f"{WEB}/collection/{collection_id}",
        headers={"User-Agent": UA, "Accept": "text/html"}, method="HEAD")
    opener = urllib.request.build_opener(_Capture)
    try:
        with opener.open(req, timeout=12) as r:
            if r.status == 200:            # 没有重定向，说明 id 本身就是规范地址
                return f"{WEB}/collection/{collection_id}", "no-redirect"
    except _Redirect as e:
        return e.url, "redirect"
    except Exception as e:                 # noqa: BLE001
        return f"{WEB}/collection/{collection_id}-{fallback_slug}", f"fallback({type(e).__name__})"
    return f"{WEB}/collection/{collection_id}-{fallback_slug}", "fallback"


def main() -> int:
    incremental = "--incremental" in sys.argv
    refresh_colls = "--refresh-collections" in sys.argv
    data = json.loads(SCAN.read_text(encoding="utf-8"))
    rows = data["rows"]
    cfg = load_config()
    t = cfg["tmdb"]
    tmdb = TMDBClient(t["api_key"], t["api_host"], t["image_host"], t["language"],
                      max(300, t["request_interval_ms"]))
    today = date.today().isoformat()

    old: dict = {}
    if incremental and OUT.exists():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"增量模式：缓存电影 {len(old.get('by_movie', {}))} 条 / "
              f"合集 {len(old.get('collections', {}))} 个")
    old_by_movie = old.get("by_movie", {})
    old_colls = old.get("collections", {})

    # ── A. 每部作品的归属合集 ───────────────────────────────
    by_movie: dict[str, dict] = {}
    series_votes: dict[str, Counter] = defaultdict(Counter)
    n_api = n_cache = 0
    for i, r in enumerate(rows, 1):
        mid = str(r["tmdb_id"])
        # 增量：缓存有效（上次查询成功，带 title 字段）则直接复用
        cached = old_by_movie.get(mid)
        if incremental and cached and "title" in cached:
            by_movie[mid] = cached
            n_cache += 1
        else:
            try:
                d = tmdb.detail(mid, "movie")
            except Exception as e:                      # noqa: BLE001
                print(f"  ! {mid} {r['title']}: {e}")
                by_movie[mid] = {"collection_id": None, "collection_name": ""}
                continue
            bc = d.get("belongs_to_collection") or {}
            by_movie[mid] = {
                "collection_id": bc.get("id"),
                "collection_name": bc.get("name") or "",
                "title": d.get("title") or d.get("name") or "",
                "original_title": d.get("original_title") or "",
                "release_date": d.get("release_date") or "",
            }
            n_api += 1
            print(f"  [{i:>3}/{len(rows)}] {r['title']:<22} → "
                  f"{by_movie[mid]['collection_id'] or '—'} "
                  f"{by_movie[mid]['collection_name']}")
        cid = by_movie[mid].get("collection_id")
        # 只对「合集」下的系列投票：『专辑』是平铺的单片桶而非系列，
        # 拿单片归属反推会把整桶专辑误挂到某部单片所属的合集上。
        if cid and r["category"] == "合集":
            series_votes[r["container"]][int(cid)] += 1
    if incremental:
        print(f"by_movie: 复用缓存 {n_cache} 条，新查 {n_api} 条")

    series: dict[str, dict] = {}
    for cont, votes in series_votes.items():
        pick, n = votes.most_common(1)[0]
        series[cont] = {
            "collection_id": pick,
            "votes": {str(k): v for k, v in votes.items()},
            "mixed": len(votes) > 1,      # 同一系列下出现了多个合集（需人工留意）
        }
    for r in rows:
        if r["category"] == "合集":
            series.setdefault(r["container"], {"collection_id": None, "votes": {}, "mixed": False})

    # ── B. 每个合集的成员与上映情况 ─────────────────────────
    coll_ids = sorted({v["collection_id"] for v in series.values() if v["collection_id"]})
    print(f"\n合集 {len(coll_ids)} 个，开始取详情…")
    collections: dict[str, dict] = {}
    n_coll_cache = 0
    todo: list[int] = []
    for cid in coll_ids:
        cached = old_colls.get(str(cid))
        if incremental and not refresh_colls and cached and cached.get("parts"):
            # 就地重算「是否已上映」（基准日可能已变），不调 API
            parts = [dict(p, released=bool(p.get("release_date"))
                          and p["release_date"] <= today)
                     for p in cached["parts"]]
            rel = sum(1 for p in parts if p["released"])
            collections[str(cid)] = dict(cached, parts=parts,
                                         count_total=len(parts),
                                         count_released=rel,
                                         count_unreleased=len(parts) - rel)
            n_coll_cache += 1
        else:
            todo.append(cid)
    if incremental:
        print(f"  复用缓存 {n_coll_cache} 个（上映状态已按 {today} 重算），"
              f"新取 {len(todo)} 个")
    for i, cid in enumerate(todo, 1):
        zh = tmdb._get(f"/collection/{cid}", {"language": "zh-CN"}) or {}
        orig = zh.get("original_name") or ""
        if not orig:                                   # 少数情况 zh 请求不带 original_name
            base = tmdb._get(f"/collection/{cid}", {}) or {}
            orig = base.get("original_name") or base.get("name") or ""
        parts = []
        for p in zh.get("parts") or []:
            rd = p.get("release_date") or ""
            parts.append({
                "id": str(p.get("id") or ""),
                "title": p.get("title") or p.get("name") or "",
                "release_date": rd,
                "released": bool(rd) and rd <= today,
            })
        parts.sort(key=lambda x: (x["release_date"] or "9999", x["title"]))
        rel = sum(1 for p in parts if p["released"])
        url, src = canonical_url(int(cid), slugify(orig))
        time.sleep(SLUG_SLEEP)
        collections[str(cid)] = {
            "id": int(cid),
            "name_zh": zh.get("name") or "",
            "original_name": orig,
            "slug": slugify(orig),
            "url": url,
            "url_source": src,
            "count_total": len(parts),
            "count_released": rel,
            "count_unreleased": len(parts) - rel,
            "parts": parts,
        }
        print(f"  [{i:>2}/{len(todo)}] {cid:<8} {collections[str(cid)]['name_zh']:<24} "
              f"共 {len(parts):>2} 已上映 {rel:>2}  url={url.split('/')[-1]} ({src})")

    OUT.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "by_movie": by_movie,
        "series": series,
        "collections": collections,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print(f"作品 {len(by_movie)}｜系列 {len(series)}｜合集 {len(collections)}")
    mixed = [k for k, v in series.items() if v["mixed"]]
    if mixed:
        print(f"⚠ 混用多个合集的系列 {len(mixed)} 个：")
        for k in mixed:
            print("   ", k, series[k]["votes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
