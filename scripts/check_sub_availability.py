#!/usr/bin/env python3
"""字幕可用性调研（只查不下载）。

对合集/专辑 262 部作品逐一查询 SubHD：
  1. GET /search/<片名 年份>      -> 取首个作品页 /d/<id>
  2. GET /d/<id>                  -> 解析字幕条目（语种/格式/版本名/点赞/下载量）

产出 data/state/sub_avail.json（增量写入，可断点续跑）：
  { "rows": [ {tmdb_id, title, year, resolution, category, container,
               work_id, work_title, entry_count,
               srt_chs, srt_en, srt_bilingual, ass_chs, ass_en,
               has_bluray_match, has_res_match, top_entries[], error?} ] }

限速 SLEEP 秒/请求，失败重试 1 次。不下载任何字幕文件。
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.config import state_path

BASE = "https://subhd.tv"
SLEEP = 2.5
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
OUT = state_path("sub_avail.json")
SCAN = state_path("container_scan.json")

LANG_KEYS = {
    "简体": "chs", "繁体": "cht", "双语": "bilingual",
    "英语": "en", "英文": "en",
}


def fetch(url: str, retries: int = 1) -> str:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(SLEEP * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def parse_search(html: str) -> list[str]:
    """搜索页 -> 候选作品 /d/<id>（按出现顺序去重，最多 3 个）。"""
    ids: list[str] = []
    for m in re.finditer(r"href='(/d/\d+)'", html):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    return ids[:3]


def parse_entries(html: str) -> list[dict]:
    """作品页 -> 字幕条目列表。"""
    entries: list[dict] = []
    # 每个条目以 <a class="link-dark" href="/a/SID">RELEASE</a> 开始
    parts = re.split(r'<a class="link-dark" href="(/a/[A-Za-z0-9]+)">', html)
    # parts: [head, sid1, block1, sid2, block2, ...]
    for i in range(1, len(parts) - 1, 2):
        sid = parts[i].split("/")[-1]
        block = parts[i + 1][:3000]
        m = re.match(r"([^<]+)</a>", block)
        release = (m.group(1).strip() if m else "")
        # 语种标签
        langs = set()
        for word, code in LANG_KEYS.items():
            if f">{word}<" in block:
                langs.add(code)
        fmt = "SRT" if ">SRT<" in block else ("ASS" if (">ASS<" in block or ">SSA<" in block) else "other")
        official = "官方字幕" in block
        likes = 0
        ml = re.search(r'align-baseline">(\d+)</span>', block)
        if ml:
            likes = int(ml.group(1))
        entries.append({
            "sid": sid, "release": release, "langs": sorted(langs),
            "fmt": fmt, "official": official, "likes": likes,
        })
    return entries


def main() -> int:
    rows = json.loads(SCAN.read_text(encoding="utf-8"))["rows"]
    done: dict[str, dict] = {}
    if OUT.exists():
        done = {r["tmdb_id"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))["rows"]}
    results = list(done.values())
    todo = [r for r in rows if str(r["tmdb_id"]) not in done]
    print(f"总数 {len(rows)}，已完成 {len(done)}，待查 {len(todo)}", flush=True)

    for idx, r in enumerate(todo, 1):
        title, year = r["title"], r.get("year")
        rec = {
            "tmdb_id": str(r["tmdb_id"]), "title": title, "year": year,
            "resolution": r.get("resolution"), "category": r["category"],
            "container": r["container"],
        }
        try:
            q = urllib.parse.quote(f"{title} {year}" if year else title)
            html = fetch(f"{BASE}/search/{q}")
            time.sleep(SLEEP)
            ids = parse_search(html)
            if not ids and year:  # 兜底：只搜片名
                html = fetch(f"{BASE}/search/{urllib.parse.quote(title)}")
                time.sleep(SLEEP)
                ids = parse_search(html)
            if not ids:
                rec["error"] = "no_work_found"
            else:
                rec["work_id"] = ids[0]
                whtml = fetch(f"{BASE}{ids[0]}")
                time.sleep(SLEEP)
                entries = parse_entries(whtml)
                rec["entry_count"] = len(entries)
                rec["srt_chs"] = sum(1 for e in entries if e["fmt"] == "SRT" and "chs" in e["langs"])
                rec["srt_en"] = sum(1 for e in entries if e["fmt"] == "SRT" and "en" in e["langs"])
                rec["srt_bilingual"] = sum(1 for e in entries if e["fmt"] == "SRT" and "bilingual" in e["langs"])
                rec["ass_chs"] = sum(1 for e in entries if e["fmt"] == "ASS" and "chs" in e["langs"])
                rec["ass_en"] = sum(1 for e in entries if e["fmt"] == "ASS" and "en" in e["langs"])
                res = (r.get("resolution") or "").lower()
                rec["has_res_match"] = any(res and res in e["release"].lower() for e in entries)
                rec["has_bluray_match"] = any(
                    "bluray" in e["release"].lower() or "remux" in e["release"].lower()
                    for e in entries)
                top = sorted(entries, key=lambda e: -e["likes"])[:3]
                rec["top_entries"] = top
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        results.append(rec)
        # 增量落盘
        OUT.write_text(json.dumps({"rows": results}, ensure_ascii=False, indent=1), encoding="utf-8")
        mark = "ERR" if rec.get("error") else f"chs={rec.get('srt_chs', 0)} en={rec.get('srt_en', 0)}"
        print(f"[{len(done)+idx}/{len(rows)}] {title} ({year}) -> {mark}", flush=True)

    # 汇总
    ok = [x for x in results if not x.get("error")]
    both = [x for x in ok if x.get("srt_chs", 0) > 0 and x.get("srt_en", 0) > 0]
    print(f"\n=== 汇总 ===\n查询成功 {len(ok)}/{len(rows)}，简中+英文 SRT 都有 {len(both)} 部", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
