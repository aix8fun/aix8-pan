#!/usr/bin/env python3
"""查询 0-待整理 各部作品的 TMDB 归属合集信息（只读）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aix8pan.config import load_config  # noqa: E402
from aix8pan.core.tmdb import TMDBClient  # noqa: E402

WORKS = [
    ("长安的荔枝", 1356587),
    ("戏台", 1406607),
    ("唐探1900", 1357305),
    ("南京照相馆", 1500536),
    ("落叶归根", 36113),
    ("浪浪山小妖怪", 1304434),
    ("蛟龙行动", 1280330),
    ("疯狂动物城2", 1084242),
    ("镖人：风起大漠", 1305781),
]

cfg = load_config()
tmdb = TMDBClient(cfg)
for name, tid in WORKS:
    try:
        d = tmdb.detail(tid, "movie")
    except TypeError:
        d = tmdb.detail("movie", tid)
    coll = d.get("belongs_to_collection")
    orig = d.get("original_title", "")
    year = (d.get("release_date") or "")[:4]
    if coll:
        print(f"{name} ({year}) tmdb={tid} orig={orig} → 合集 {coll['id']} {coll['name']}")
    else:
        print(f"{name} ({year}) tmdb={tid} orig={orig} → 无合集（专辑）")
