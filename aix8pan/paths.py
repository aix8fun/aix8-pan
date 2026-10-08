"""路径锚定：工程根与持久状态目录。

所有管线的中间状态（container_scan.json / tmdb_collections.json /
115_cids.json / 字幕状态等）统一放 data/state/ —— 早期放在 /tmp，
重启即丢导致增量管线退化为全量（2026-10-08 修正）。
用法（任何脚本，任何 cwd）:
    from aix8pan.paths import state_path
    SCAN = state_path("container_scan.json")
"""
from __future__ import annotations

from pathlib import Path

# 工程根 = aix8pan/ 的上一级
ROOT = Path(__file__).resolve().parent.parent

# 持久状态目录（随工程保存）
STATE_DIR = ROOT / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# 历史遗留：/tmp 下可能有旧状态文件，首次用到时顺手搬过来
_LEGACY_TMP = Path("/tmp")


def state_path(name: str) -> Path:
    """返回 data/state/<name>；若 /tmp/<name> 存在而本地没有，则搬迁。"""
    p = STATE_DIR / name
    if not p.exists():
        old = _LEGACY_TMP / name
        if old.is_file():
            try:
                old.replace(p)
            except OSError:
                pass
    return p
