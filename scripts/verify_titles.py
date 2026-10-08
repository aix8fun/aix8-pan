#!/usr/bin/env python
"""全量核对：作品目录名标题 vs TMDB 官方中文标题（**只读**）。

对 data/state/container_scan.json 里每个带 tmdb_id 的作品查 TMDB 中文标题，
归一化后比对，找出「标题不一致 / 目录名掺入额外修饰词 / 缺中文名」三类问题。

输出: data/state/title_verify.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.config import state_path

from aix8pan.config import load_config
from aix8pan.core.tmdb import TMDBClient, norm_meta

BRACKET_RE = re.compile(r"[（(][^）)]*[）)]")
STRIP_RE = re.compile(r"[\s\-–—_:,，.。·！!？?、\[\]（）()]")


def norm(s: str) -> str:
    return STRIP_RE.sub("", (s or "").replace("：", ":")).lower()


def has_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def main() -> int:
    rows = json.loads(state_path("container_scan.json").read_text(encoding="utf-8"))["rows"]
    c = load_config()["tmdb"]
    t = TMDBClient(c["api_key"], c["api_host"], c["image_host"], c["language"],
                   c["request_interval_ms"])

    out = []
    for i, r in enumerate(rows, 1):
        mid = r.get("tmdb_id") or ""
        cur = r.get("title") or ""
        rec = {"category": r["category"], "container": r["container"],
               "folder": r["folder_raw"], "title": cur, "tmdb_id": mid,
               "tmdb_title": "", "issues": []}
        if not mid:
            rec["issues"].append("NO_TMDB_ID")
        else:
            try:
                m = norm_meta(t.detail(mid, "movie"), "movie")
                tt = (m.get("title") or "").strip()
                rec["tmdb_title"] = tt
                if not tt:
                    rec["issues"].append("TMDB_NO_TITLE")
                elif norm(tt) != norm(cur):
                    # 目录名标题是否被括在 TMDB 标题之外的额外段污染
                    extra = cur
                    for part in [tt, BRACKET_RE.sub("", tt)]:
                        extra = extra.replace(part, "")
                    extra = BRACKET_RE.sub("", extra).strip(" -–—")
                    if extra and len(norm(extra)) <= 20 and (
                            re.search(r"\s+-\s+", cur) or re.search(r"[A-Za-z]{3,}", extra)):
                        rec["issues"].append("EXTRA_SEGMENT")
                    else:
                        rec["issues"].append("TITLE_MISMATCH")
            except Exception as e:                        # noqa: BLE001
                rec["issues"].append(f"ERR:{e}")
        if not has_cjk(cur):
            rec["issues"].append("NO_CJK_TITLE")
        out.append(rec)          # 全量输出：表格需要每行的 TMDB 官方名
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}", file=sys.stderr, flush=True)

    dest = state_path("title_verify.json")
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [r for r in out if r["issues"]]
    print(f"\n核对 {len(rows)} 部，有问题 {len(bad)} 部 → {dest}")
    codes: dict[str, int] = {}
    for r in bad:
        for c_ in r["issues"]:
            codes[c_] = codes.get(c_, 0) + 1
    print("问题码分布:", codes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
