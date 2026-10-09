"""配置加载：环境变量优先，config.json 本地覆盖，内置默认兜底

分发型配置（用户在 MCP 配置的 env 字段填写，见 README「部署引导」）：
  OPENLIST_URL    OpenList 服务地址，如 https://pan.aix8.fun
  OPENLIST_USER   OpenList 用户名，如 admin
  OPENLIST_PASS   OpenList 密码
  TMDB_HOST       TMDB API 地址（官方 https://api.themoviedb.org 或自建代理）
  TMDB_API_KEY    TMDB API Key（32 位）

优先级：环境变量 > config.json > 内置默认值。
config.json 只存非敏感的本机偏好（库路径 / 命名模板 / 限速），
凭据一律走环境变量，绝不落盘到工程目录。

本模块同时承担路径锚定（data/ 下 plans · cache · state 三个子目录），
管线中间状态统一持久化在 data/state/（不要放 /tmp，重启即丢）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 工程根 = aix8pan/ 的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


def _resolve_data_dir() -> Path:
    """数据目录锚定：
    ① 环境变量 AIX8PAN_DATA_DIR 显式指定；
    ② 开发模式（工程根有 .git 或 config.json）→ 工程内 data/；
    ③ 发行模式（pip/uvx 装进 site-packages）→ ~/.aix8pan/，
       避免写进 uv 缓存区（包升级即清空，方案存档会丢）。
    """
    env = os.environ.get("AIX8PAN_DATA_DIR")
    if env:
        return Path(env)
    if (PROJECT_ROOT / ".git").exists() or CONFIG_PATH.exists():
        return PROJECT_ROOT / "data"
    return Path.home() / ".aix8pan"


DATA_DIR = _resolve_data_dir()
PLANS_DIR = DATA_DIR / "plans"
CACHE_DIR = DATA_DIR / "cache"
STATE_DIR = DATA_DIR / "state"

# 环境变量 → 配置键 映射（TMDB_HOST 同时供给 api_host 与 image_host；
# 需要两者不同时，请只在 config.json 配 tmdb.image_host，不设 TMDB_HOST env）
_ENV_OVERRIDES: dict[tuple[str, str], str] = {
    ("openlist", "base_url"): "OPENLIST_URL",
    ("openlist", "username"): "OPENLIST_USER",
    ("openlist", "password"): "OPENLIST_PASS",
    ("tmdb", "api_key"): "TMDB_API_KEY",
    ("tmdb", "api_host"): "TMDB_HOST",
    ("tmdb", "image_host"): "TMDB_HOST",
}

# 历史遗留：/tmp 下可能有旧状态文件，首次用到时顺手搬过来
_LEGACY_TMP = Path("/tmp")


def state_path(name: str) -> Path:
    """返回 data/state/<name>；若 /tmp/<name> 存在而本地没有，则搬迁。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / name
    if not p.exists():
        old = _LEGACY_TMP / name
        if old.is_file():
            try:
                old.replace(p)
            except OSError:
                pass
    return p


def _default_naming() -> dict[str, Any]:
    """命名模板默认值取自单一事实源（core/naming_spec），保证开箱即合规。"""
    from .core.naming_spec import (
        MOVIE_FILE_TEMPLATE, MOVIE_FOLDER_TEMPLATE, SEASON_FOLDER_TEMPLATE,
        TV_FILE_TEMPLATE, TV_FOLDER_TEMPLATE,
    )
    return {
        "movie_folder_template": MOVIE_FOLDER_TEMPLATE,
        "tv_folder_template": TV_FOLDER_TEMPLATE,
        "season_folder_template": SEASON_FOLDER_TEMPLATE,
        "movie_file_template": MOVIE_FILE_TEMPLATE,
        "tv_file_template": TV_FILE_TEMPLATE,
        "episode_title_in_file": True,
        "normalize_artwork": True,
        "keep_original_title": True,
    }


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike | None = None) -> dict:
    """读配置：内置默认值 → config.json 覆盖 → 环境变量覆盖（最高）。"""
    p = Path(path) if path else CONFIG_PATH
    user_cfg: dict = {}
    if p.exists():
        user_cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg = _deep_merge({
        "openlist": {
            "base_url": "",
            "username": "",
            "password": "",
            "op_interval_ms": 700,
        },
        "tmdb": {
            "api_key": "",
            "api_host": "https://api.themoviedb.org",
            "image_host": "https://image.tmdb.org",
            "language": "zh-CN",
            "request_interval_ms": 250,
        },
        "paths": {
            "movies": "/115/01-电影",
            "tv": "/115/02-剧集",
            "anime": "/115/03-动画",
            "doc": "/115/04-纪录片",
            "tv_rural": "/115/12-乡村剧",
        },
        "naming": _default_naming(),
        "organize": {
            # 剧集形态统一（2026-10-09）：季目录只留视频+字幕，剧根只留标准
            # 5 件套（poster/fanart/clearlogo/seasonNN-poster/tvshow.nfo）。
            # 整理时自动删除下载源自带的集级 nfo/-thumb 和旧工具残料。
            "tv_purge_companions": True,
        },
        "containers": {
            "series_suffix": "（系列）",
            "mainline_suffix": "（主线）",
            "fixed": ["0-待整理", "合集", "专辑"],
            "inbox": ["0-待整理", "待整理"],
            "drain_inbox": True,
            "include_containers": False,
        },
        "limits": {"max_execute_batch": 200, "confirm_required": True},
    }, user_cfg)
    for (section, key), env_name in _ENV_OVERRIDES.items():
        val = os.environ.get(env_name, "")
        if val:
            cfg.setdefault(section, {})[key] = val
    return cfg


def ensure_dirs() -> None:
    for d in (DATA_DIR, PLANS_DIR, CACHE_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
