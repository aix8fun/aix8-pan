"""一次性任务脚本：刮削 /115/01-电影 下指定的若干部作品。

用法：
    python3 scripts/run_scrape.py                 # 刮削根目录下缺图的作品
    python3 scripts/run_scrape.py "作品目录名" ...  # 刮削指定作品
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.config import load_config
from aix8pan.core.openlist import OpenListClient
from aix8pan.core.parser import find_tmdb_id
from aix8pan.pipeline.scraper import Scraper
from aix8pan.core.tmdb import TMDBClient

MOVIE_ROOT = "/115/01-电影"


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
        names = [e["name"] for e in client.list_all(MOVIE_ROOT, refresh=True)
                 if e.get("is_dir") and not e["name"].startswith(("0-", "合集", "专辑"))]

    for name in names:
        path = f"{MOVIE_ROOT}/{name}"
        tid = find_tmdb_id(name)
        try:
            r = scraper.scrape(path, media_type="movie", tmdb_id=tid)
        except Exception as e:
            print(f"[FAIL] {name}  {type(e).__name__}: {e}")
            continue
        if not r.get("ok"):
            print(f"[FAIL] {name}  {r.get('error')}")
            continue
        print(f"[OK]   {r['title']} ({r['year']})  tmdb={r['tmdb_id']}")
        print(f"       上传: {r['uploaded'] or '无'}")
        print(f"       跳过: {r['skipped'] or '无'}")


if __name__ == "__main__":
    main()
