#!/usr/bin/env python3
"""检查浪浪山小妖怪 TMDB 是否有 backdrop 可图。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aix8pan.config import load_config  # noqa: E402
from aix8pan.core.tmdb import TMDBClient  # noqa: E402

cfg = load_config()
t = cfg["tmdb"]
tmdb = TMDBClient(t["api_key"], t["api_host"], t["image_host"], t["language"],
                  t["request_interval_ms"])
d = tmdb.detail("1304434", "movie")
print("backdrop_path:", d.get("backdrop_path"))
try:
    imgs = tmdb.images("1304434", "movie")
    print("backdrops:", len(imgs.get("backdrops", [])))
    for b in imgs.get("backdrops", [])[:5]:
        print("  ", b.get("file_path"), b.get("width"), "x", b.get("height"))
except AttributeError:
    import json
    import urllib.request
    url = (f"https://{t['api_host']}/3/movie/1304434/images"
           f"?api_key={t['api_key']}")
    with urllib.request.urlopen(url) as r:
        imgs = json.load(r)
    print("backdrops:", len(imgs.get("backdrops", [])))
    for b in imgs.get("backdrops", [])[:5]:
        print("  ", b.get("file_path"), b.get("width"), "x", b.get("height"))
