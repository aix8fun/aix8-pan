#!/usr/bin/env python3
"""限流冷却守门 + 字幕下载启动器。

SubHD 下载接口限流恢复前不启动批量下载，避免空转：
  1. 先静默冷却 COOLDOWN 秒
  2. 用黑寡妇的 sid 探测 prepare-download
  3. 仍 403 则再等多轮（PROBE_INTERVAL × MAX_PROBES）
  4. 恢复后 exec fetch_subtitles.py --download
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_subtitles import BASE, _new_opener  # noqa: E402

COOLDOWN = 420          # 先静默 7 分钟（加上此前已停的 ~8 分钟，共 ~15 分钟）
PROBE_INTERVAL = 600    # 探测间隔 10 分钟
MAX_PROBES = 12         # 最多探 12 轮（2 小时）
PROBE_SID = "DckAZP"    # 黑寡妇 zh-CN 条目


def probe() -> bool:
    opener = _new_opener()
    try:
        opener.open(f"{BASE}/a/{PROBE_SID}", timeout=20).read()
        req = urllib.request.Request(
            f"{BASE}/api/sub/prepare-download",
            data=json.dumps({"sid": PROBE_SID}).encode(),
            headers={"Content-Type": "application/json; charset=utf-8"})
        d = json.loads(opener.open(req, timeout=20).read().decode("utf-8", errors="replace"))
        return bool(d.get("success"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"  探测: HTTP {e.code} {body[:80]}", flush=True)
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  探测异常: {e}", flush=True)
        return False


def main() -> int:
    print(f"静默冷却 {COOLDOWN}s…", flush=True)
    time.sleep(COOLDOWN)
    for i in range(MAX_PROBES + 1):
        print(f"[{time.strftime('%H:%M:%S')}] 探测 SubHD 下载接口…", flush=True)
        if probe():
            print("✅ 限流已恢复，启动批量下载", flush=True)
            return subprocess.call(
                [sys.executable, str(Path(__file__).resolve().parent / "fetch_subtitles.py"),
                 "--download"])
        if i < MAX_PROBES:
            print(f"  仍限流，{PROBE_INTERVAL}s 后再探（{i+1}/{MAX_PROBES}）", flush=True)
            time.sleep(PROBE_INTERVAL)
    print("❌ 超过最大等待，放弃；请稍后手动重跑 fetch_subtitles.py --download", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
