#!/usr/bin/env python3
"""补刮浪浪山小妖怪的 fanart。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aix8pan.pipeline.scraper import Scraper  # noqa: E402

s = Scraper()
r = s.scrape("/115/01-电影/专辑/浪浪山小妖怪 (2025) {tmdbid-1304434}",
             media_type="movie", tmdb_id="1304434")
print("ok:", r.get("ok"))
print("uploaded:", r.get("uploaded"))
print("skipped:", r.get("skipped"))
print("error:", r.get("error"))
