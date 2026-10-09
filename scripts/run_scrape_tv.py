"""批量刮削 /115/02-剧集 下的作品目录（poster/fanart/clearlogo/seasonNN-poster/tvshow.nfo）。

用法：
    python3 scripts/run_scrape_tv.py                # 刮削剧集库全部作品（已存在自动跳过）
    python3 scripts/run_scrape_tv.py "目录名" ...    # 只刮指定作品
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.config import load_config
from aix8pan.core.openlist import OpenListClient
from aix8pan.core.parser import find_tmdb_id
from aix8pan.pipeline.scraper import Scraper
from aix8pan.core.tmdb import TMDBClient

TV_ROOT = "/115/02-剧集"


def build_scraper():
    cfg = load_config()
    ol = cfg["openlist"]
    client = OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
    t = cfg["tmdb"]
    tmdb = TMDBClient(t["api_key"], t["api_host"], t["image_host"], t["language"],
                      t["request_interval_ms"])
    return Scraper(cfg, client, tmdb), client


def main():
    scraper, client = build_scraper()
    names = sys.argv[1:]
    if not names:
        names = [e["name"] for e in client.list_all(TV_ROOT, refresh=True)
                 if e.get("is_dir") and not e["name"].startswith(("0-", "合集", "专辑"))]

    ok = fail = 0
    for name in names:
        path = f"{TV_ROOT}/{name}"
        tid = find_tmdb_id(name)
        try:
            r = scraper.scrape(path, media_type="tv", tmdb_id=tid)
        except Exception as e:
            print(f"[FAIL] {name}  {type(e).__name__}: {e}", flush=True)
            fail += 1
            continue
        if not r.get("ok"):
            print(f"[FAIL] {name}  {r.get('error')}", flush=True)
            fail += 1
            continue
        ok += 1
        print(f"[OK]   {r.get('title', name)} ({r.get('year', '')})  tmdb={r.get('tmdb_id')}", flush=True)
        print(f"       上传: {r.get('uploaded') or '无'}", flush=True)
        print(f"       跳过: {r.get('skipped') or '无'}", flush=True)
    print(f"完成：{ok} 成功 / {fail} 失败", flush=True)


if __name__ == "__main__":
    main()
