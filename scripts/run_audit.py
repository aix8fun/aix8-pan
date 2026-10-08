#!/usr/bin/env python3
"""库审计脚本（只读）：扫描网盘作品目录，报告与命名规范的偏差。

用法:
    python scripts/run_audit.py /115/01-电影
    python scripts/run_audit.py /115/02-剧集 tv
    python scripts/run_audit.py /115/01-电影 --json out.json

只调用 list/parse，绝不产生任何写操作。
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.auditor import Auditor


def main() -> int:
    argv = sys.argv[1:]
    json_out = ""
    rest: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--json" and i + 1 < len(argv):
            json_out = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    root = rest[0] if rest else "/115/01-电影"
    media_type = rest[1] if len(rest) > 1 else "auto"

    r = Auditor().audit(root, media_type, include_containers=True)
    s = r["summary"]
    print(f"审计 {root}（media_type={media_type}）")
    print(f"  作品 {s['works']} 个 | 合规 {s['ok']} | 有偏差 {s['nonconforming']}"
          f" | error {s['errors']} / warn {s['warns']}")
    if r["by_code"]:
        print("  问题分布：" + "，".join(
            f"{k}×{v}" for k, v in sorted(r["by_code"].items(), key=lambda kv: -kv[1])))
    for w in r["issues"]:
        cnt = collections.Counter(i["code"] for i in w["issues"])
        print(f"\n- [{w['kind']}] {w['path']}")
        print("   " + "，".join(f"{k}×{v}" for k, v in cnt.items()))
        for it in w["issues"][:8]:
            print(f"     ({it['level']}) {it['code']}: {it['detail']}")
            if it["suggestion"]:
                print(f"        → {it['suggestion']}")
        if len(w["issues"]) > 8:
            print(f"     ...共 {len(w['issues'])} 条")
    if json_out:
        Path(json_out).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完整报告已写入 {json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
