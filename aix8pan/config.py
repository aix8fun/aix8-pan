"""配置加载：工程根目录 config.json

凭据优先级：环境变量 > config.json > 内置默认值。
  AIX8PAN_OPENLIST_PASSWORD  OpenList 登录密码
  AIX8PAN_TMDB_API_KEY       TMDB API Key
config.json 不再存放凭据（纯环境描述，可分享可备份）。
"""
import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
DATA_DIR = PROJECT_ROOT / "data"
PLANS_DIR = DATA_DIR / "plans"
CACHE_DIR = DATA_DIR / "cache"

_ENV_OVERRIDES = {
    ("openlist", "password"): "AIX8PAN_OPENLIST_PASSWORD",
    ("tmdb", "api_key"): "AIX8PAN_TMDB_API_KEY",
}

_DEFAULTS: dict[str, Any] = {
    "openlist": {
        "base_url": "https://your-openlist.example.com",
        "username": "admin",
        "password": "",
        "op_interval_ms": 700,
    },
    "tmdb": {
        "api_key": "",
        "api_host": "https://tmdb.aws360.cn",
        "image_host": "https://tmdb.aws360.cn",
        "language": "zh-CN",
        "request_interval_ms": 250,
    },
    "paths": {},
    "naming": {},
    "limits": {"max_execute_batch": 200, "confirm_required": True},
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
    p = Path(path) if path else CONFIG_PATH
    user_cfg: dict = {}
    if p.exists():
        user_cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg = _deep_merge(_DEFAULTS, user_cfg)
    for (section, key), env_name in _ENV_OVERRIDES.items():
        val = os.environ.get(env_name, "")
        if val:
            cfg.setdefault(section, {})[key] = val
    return cfg


def ensure_dirs() -> None:
    for d in (DATA_DIR, PLANS_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
