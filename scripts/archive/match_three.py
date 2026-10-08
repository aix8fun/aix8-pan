#!/usr/bin/env python3
"""确认三部根目录散件的 TMDB 匹配。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aix8pan.config import load_config  # noqa: E402
from aix8pan.tmdb import TMDBClient  # noqa: E402

cfg = load_config()
t = cfg["tmdb"]
tmdb = TMDBClient(t["api_key"], t["api_host"], t["image_host"], t["language"],
                  t["request_interval_ms"])
for title, year in [("惊天魔盗团3", "2025"), ("疯狂动物城", "2016"),
                    ("侏罗纪世界：重生", "2025")]:
    m = tmdb.match(title, year, "movie")
    if not m:
        print(f"{title} ({year}) → 未匹配")
        continue
    d = tmdb.detail(str(m["id"]), "movie")
    coll = d.get("belongs_to_collection") or {}
    print(f"{title} ({year}) → tmdb={m['id']}  中文名={d.get('title')}  "
          f"原名={d.get('original_title')}  合集={coll.get('id')} {coll.get('name')}")
