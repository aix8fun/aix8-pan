#!/usr/bin/env python
"""把 `title_segment_issues`（FOLDER_EXTRA_SEG / FOLDER_NO_CJK）离线补进扫描结果。

避免为了两条纯字符串规则重跑一遍全量网盘扫描。
原地更新 data/state/container_scan.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.config import state_path

from aix8pan.pipeline.auditor import title_segment_issues

SRC = state_path("container_scan.json")
CODES = {"FOLDER_EXTRA_SEG", "FOLDER_NO_CJK"}


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    added = 0
    for r in data["rows"]:
        issues = [i for i in r["issues"] if i["code"] not in CODES]
        extra = title_segment_issues(r["folder_raw"], r["year"])
        if extra:
            issues.extend(extra)
            added += len(extra)
        r["issues"] = issues
        r["errors"] = [i["detail"] for i in issues if i["level"] == "error"]
        r["warns"] = [i["detail"] for i in issues if i["level"] == "warn"]
        r["infos"] = [i["detail"] for i in issues if i["level"] == "info"]
        r["n_err"] = len(r["errors"])
        r["n_warn"] = len(r["warns"])
        r["n_info"] = len(r["infos"])
        r["conform"] = r["n_err"] == 0 and r["n_warn"] == 0
        r["info_only"] = r["conform"] and r["n_info"] > 0
    data["conform"] = sum(1 for r in data["rows"] if r["conform"])
    SRC.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"补检新增 {added} 条 | 合规 {data['conform']}/{data['total']}")
    for r in data["rows"]:
        if not r["conform"]:
            print(f"  [{r['category']}] {r['folder_raw']}")
            for i in r["issues"]:
                print(f"      ({i['level']}) {i['code']}: {i['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
