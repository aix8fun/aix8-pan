#!/usr/bin/env python3
"""字幕可用性补查：对首轮 no_work_found 的条目，改用 TMDB 英文原名重查。

读取 data/state/sub_avail.json，对 error 条目用 original_title + year 重新搜索 SubHD，
成功则覆盖该条目（清除 error），增量写回同一文件。
限速 3s/请求，比首轮更保守。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from aix8pan.config import state_path
from check_sub_availability import BASE, OUT, fetch, parse_entries, parse_search  # noqa: E402

SLEEP = 3.0
TMDB = state_path("tmdb_collections.json")


def main() -> int:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    rows = data["rows"]
    by_movie = json.loads(TMDB.read_text(encoding="utf-8"))["by_movie"]

    todo = [r for r in rows if r.get("error")]
    print(f"待补查 {len(todo)} 部", flush=True)
    fixed = 0
    for idx, rec in enumerate(todo, 1):
        info = by_movie.get(rec["tmdb_id"]) or {}
        orig = info.get("original_title") or ""
        year = rec.get("year")
        if not orig:
            print(f"[{idx}/{len(todo)}] {rec['title']} 无英文原名，跳过", flush=True)
            continue
        try:
            q = urllib.parse.quote(f"{orig} {year}" if year else orig)
            html = fetch(f"{BASE}/search/{q}")
            time.sleep(SLEEP)
            ids = parse_search(html)
            if not ids and year:
                html = fetch(f"{BASE}/search/{urllib.parse.quote(orig)}")
                time.sleep(SLEEP)
                ids = parse_search(html)
            if not ids:
                print(f"[{idx}/{len(todo)}] {rec['title']} ({orig}) 仍无结果", flush=True)
                continue
            whtml = fetch(f"{BASE}{ids[0]}")
            time.sleep(SLEEP)
            entries = parse_entries(whtml)
            rec.pop("error", None)
            rec["work_id"] = ids[0]
            rec["entry_count"] = len(entries)
            rec["srt_chs"] = sum(1 for e in entries if e["fmt"] == "SRT" and "chs" in e["langs"])
            rec["srt_en"] = sum(1 for e in entries if e["fmt"] == "SRT" and "en" in e["langs"])
            rec["srt_bilingual"] = sum(1 for e in entries if e["fmt"] == "SRT" and "bilingual" in e["langs"])
            rec["ass_chs"] = sum(1 for e in entries if e["fmt"] == "ASS" and "chs" in e["langs"])
            rec["ass_en"] = sum(1 for e in entries if e["fmt"] == "ASS" and "en" in e["langs"])
            res = (rec.get("resolution") or "").lower()
            rec["has_res_match"] = any(res and res in e["release"].lower() for e in entries)
            rec["has_bluray_match"] = any(
                "bluray" in e["release"].lower() or "remux" in e["release"].lower()
                for e in entries)
            rec["top_entries"] = sorted(entries, key=lambda e: -e["likes"])[:3]
            fixed += 1
            print(f"[{idx}/{len(todo)}] {rec['title']} ({orig}) -> "
                  f"chs={rec['srt_chs']} en={rec['srt_en']}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{idx}/{len(todo)}] {rec['title']} ({orig}) 查询失败: {e}", flush=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    err_left = [r for r in rows if r.get("error")]
    both = [r for r in rows if not r.get("error")
            and r.get("srt_chs", 0) > 0 and r.get("srt_en", 0) > 0]
    print(f"\n=== 补查完成 === 修复 {fixed} 部，仍失败 {len(err_left)} 部，"
          f"简中+英文都有 {len(both)}/{len(rows)}", flush=True)
    for r in err_left:
        print("  仍失败:", r["title"], r.get("year"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
