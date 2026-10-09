"""本地跑 build_plan（与 MCP 工具同入口同参数），绕开常驻 MCP 进程的旧代码。

用法:
    python3 scripts/run_build_plan.py <source> [target_root] [media_type] [--strict]

说明:
- 与 server.build_plan 完全一致：Planner.build_plan(...) + save_plan。
- 供修改 aix8pan 源码后无需重启 MCP 连接器即可用新逻辑生成方案。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.pipeline.planner import Planner


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("target_root", nargs="?", default="")
    ap.add_argument("media_type", nargs="?", default="auto")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--include-containers", action="store_true")
    args = ap.parse_args()

    planner = Planner()
    plan = planner.build_plan(args.source, args.target_root or None, args.media_type,
                              include_containers=args.include_containers,
                              drain_inbox=True, normalize_names=True,
                              strict=args.strict)
    planner.save_plan(plan)
    s = plan["summary"]
    print(json.dumps({"plan_id": plan["plan_id"], "summary": s,
                      "unmatched": plan["unmatched"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
