"""分批执行超限 Plan：把 actions 切成 <=200 的块逐块执行，块间落盘断点续跑。

用法:
    python3 scripts/run_plan_batched.py <plan_id> [--batch 200]

说明:
- Executor 单次上限 max_execute_batch（默认 200），本脚本只是循环喂块，
  每个动作仍走 Executor 原有逻辑（限速 / 重试 / 幂等），安全性一致。
- 每块执行完立即 update_plan 落盘；动作级 status=done 原地标记，
  中断后重跑会自动跳过已完成动作。
- mkdir 结构性失败时 Executor 会中断该块，本脚本检测到失败即整体停止，
  不硬闯，把现场留在 plan 文件里。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.pipeline.executor import Executor
from aix8pan.pipeline.planner import Planner


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_id")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    planner = Planner()
    executor = Executor()
    plan = planner.load_plan(args.plan_id)
    actions = plan.get("actions") or []
    total = len(actions)
    print(f"Plan {args.plan_id}: {total} 个动作，分批大小 {args.batch}", flush=True)

    done_total = sum(1 for a in actions if a.get("status") == "done")
    failed_total = 0
    errors: list[str] = []

    pending = [a for a in actions if a.get("status") != "done"]
    chunks = [pending[i:i + args.batch] for i in range(0, len(pending), args.batch)]
    for ci, chunk in enumerate(chunks, 1):
        sub = {"actions": chunk}
        t0 = time.time()
        result = executor.execute(sub, confirm=True)
        planner.update_plan(plan)  # 每块落盘，断点续跑
        done_total += result["done"]
        failed_total += result["failed"]
        errors.extend(result.get("errors") or [])
        print(f"[批 {ci}/{len(chunks)}] done={result['done']} failed={result['failed']} "
              f"累计 {done_total}/{total} 用时 {time.time() - t0:.0f}s", flush=True)
        if result["failed"]:
            print("出现失败，整体停止。错误样本：", flush=True)
            for e in (result.get("errors") or [])[:10]:
                print(f"  - {e}", flush=True)
            plan["status"] = "partial"
            planner.update_plan(plan)
            return 1

    plan["status"] = "executed"
    plan["executed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    planner.update_plan(plan)
    print(f"全部完成：{done_total} done / {failed_total} failed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
