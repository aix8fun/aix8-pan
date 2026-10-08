"""aix8pan.core — 基础能力层

命名规范事实源（naming_spec） / 命名引擎（naming） / 文件名解析（parser）
OpenList 客户端（openlist） / TMDB 客户端（tmdb）。

刻意保持本 __init__ 为空壳：config.py 会 import 本包的 naming_spec，
若此处再 import 依赖 config 的子模块（如 tmdb）会形成环。
"""
