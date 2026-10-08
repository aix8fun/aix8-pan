"""AIX8-Pan MCP Server（stdio）

暴露给 WorkBuddy 的原子工具集：
  浏览:  list_dir / search_files / get_paths / get_download_url
  识别:  parse_name / naming_spec / tmdb_search / tmdb_detail
  整理:  build_plan / preview_plan / execute_plan（必须显式确认）
  刮削:  scrape_dir
  审计:  audit_library（只读，报告命名规范偏差）
  运维:  health_check

安全铁律：
  - execute_plan 需要用户在对话中明确确认后才可传 confirm=true
  - 所有写操作经 OpenList 客户端限速（默认 700ms/操作）

输出契约：
  - 全部工具返回统一信封 Result（TypedDict）——成功 {ok: True, data: ...}，
    失败 {ok: False, error: ...}；SDK 据此发布 outputSchema 并把结果写入
    structuredContent（宿主可结构化消费），文本通道保留同样的 JSON（向后兼容）。
  - data 的具体形态见各工具 description；人类可读的摘要放在 data.detail 字段。
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any, NotRequired, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from aix8pan import __version__
from aix8pan.config import load_config, ensure_dirs
from aix8pan.core import naming_spec
from aix8pan.core.naming import NamingEngine
from aix8pan.core.openlist import OpenListClient
from aix8pan.core.parser import parse_media_name
from aix8pan.core.tmdb import TMDBClient
from aix8pan.pipeline.auditor import Auditor
from aix8pan.pipeline.executor import Executor
from aix8pan.pipeline.planner import Planner
from aix8pan.pipeline.scraper import Scraper

ensure_dirs()

_cfg = load_config()
_ol = _cfg["openlist"]
_tm = _cfg["tmdb"]
client = OpenListClient(_ol["base_url"], _ol["username"], _ol["password"], _ol["op_interval_ms"])
tmdb = TMDBClient(_tm["api_key"], _tm["api_host"], _tm["image_host"], _tm["language"],
                  _tm["request_interval_ms"])
planner = Planner(_cfg, client, tmdb)
executor = Executor(_cfg, client)
scraper = Scraper(_cfg, client, tmdb)
auditor = Auditor(_cfg, client)

server = MCPServer(name="aix8-pan",
                   version=__version__,
                   title="AIX8-Pan 115 网盘整理",
                   instructions="115 网盘媒体整理助手：浏览/识别/规划/审计/刮削。整理走 Plan→确认→Execute 流程，绝不直接改文件。"
                               "命名规范以 naming_spec 为唯一标准；其中**电影规则已于 v2.0 冻结**"
                               "（2026-10-07），处理电影一律按冻结条款，不得擅自「优化」命名形态。")


class Result(TypedDict):
    """统一返回信封（同时是 14 个工具的 outputSchema 根）。

    成功 {ok: True, data: ...}；失败 {ok: False, error: ...}。
    不用 Union[成功, 失败] 两个 TypedDict —— Union 返回会被 SDK 包进
    {"result": ...} 包装层，structuredContent 形态变丑。
    """
    ok: bool
    data: NotRequired[Any]
    error: NotRequired[str]


def _jsonable(data: Any) -> Any:
    """保证 structuredContent 是合法 JSON（datetime/Path 等兜底转 str）。"""
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def _ok(data: Any) -> Result:
    return {"ok": True, "data": _jsonable(data)}


def _err(msg: object) -> Result:
    return {"ok": False, "error": str(msg)[:500]}


# MCP 工具注解：宿主据此做权限提示与审批策略
# 纯读（含网盘/TMDB 查询，不改任何状态）
A_READONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                             idempotentHint=True, openWorldHint=True)
# 只写本地方案文件，不碰网盘
A_PLAN = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                         idempotentHint=False, openWorldHint=True)
# 写网盘（移动/改名/删除），失败可断点续跑（幂等）
A_EXECUTE = ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                            idempotentHint=True, openWorldHint=True)
# 写网盘（上传海报/nfo；cleanup_legacy 会删旧图），已存在自动跳过（幂等）
A_SCRAPE = ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                           idempotentHint=True, openWorldHint=True)


# ---------------- 浏览 ----------------

@server.tool(description="列出网盘目录内容。path 如 /115/01-电影。refresh=true 强刷缓存。",
             annotations=A_READONLY)
def list_dir(path: str, refresh: bool = False) -> Result:
    try:
        items = client.list_all(path, refresh=refresh)
        out = [{"name": i.get("name"), "is_dir": i.get("is_dir"),
                "size": i.get("size"), "modified": i.get("modified")} for i in items]
        return _ok({"path": path, "count": len(out), "items": out})
    except Exception as e:
        return _err(e)


@server.tool(description="在指定目录下按关键字搜索（当前层及子层）。",
             annotations=A_READONLY)
def search_files(parent: str, keywords: str) -> Result:
    try:
        items = client.search(parent, keywords)
        return _ok([{"name": i.get("name"), "parent": i.get("parent"),
                     "is_dir": i.get("is_dir")} for i in items])
    except Exception as e:
        return _err(e)


@server.tool(description="获取配置的网盘路径映射（电影库/剧集库/动画库等）。",
             annotations=A_READONLY)
def get_paths() -> Result:
    return _ok(_cfg.get("paths") or {})


@server.tool(description="取文件下载直链（供 ffprobe 探测等用途）。",
             annotations=A_READONLY)
def get_download_url(path: str) -> Result:
    try:
        return _ok({"url": client.get_download_url(path)})
    except Exception as e:
        return _err(e)


# ---------------- 识别 ----------------

@server.tool(description="查看统一命名规范（模板 / artwork 命名 / 技术标签顺序 / 容器规则）。"
                         "任何命名疑问都以此为准。",
             annotations=A_READONLY)
def naming_spec_tool() -> Result:
    return _ok(naming_spec.spec_dict())


@server.tool(description="解析文件名：标题/年份/季集/技术标签/TMDB ID。用于预判整理效果。",
             annotations=A_READONLY)
def parse_name(name: str, is_dir: bool = False) -> Result:
    p = parse_media_name(name, is_dir=is_dir)
    return _ok({"title": p.title, "year": p.year, "season": p.season, "episode": p.episode,
                "tmdb_id": p.tmdb_id, "tech": p.tech, "resolution": p.resolution,
                "is_media": p.is_media, "is_companion": p.is_companion, "ext": p.ext})


@server.tool(description="TMDB 搜索。media_type: movie/tv/auto。返回候选列表。",
             annotations=A_READONLY)
def tmdb_search(title: str, year: str = "", media_type: str = "auto") -> Result:
    try:
        res = tmdb.search(title, year, media_type)
        out = {}
        for kind, items in res.items():
            out[kind] = [{"id": i.get("id"),
                          "title": i.get("title") or i.get("name"),
                          "original": i.get("original_title") or i.get("original_name"),
                          "date": i.get("release_date") or i.get("first_air_date"),
                          "overview": (i.get("overview") or "")[:100]} for i in items[:8]]
        return _ok(out)
    except Exception as e:
        return _err(e)


@server.tool(description="TMDB 详情（含季信息/图片路径）。",
             annotations=A_READONLY)
def tmdb_detail(tmdb_id: str, media_type: str) -> Result:
    try:
        d = tmdb.detail(tmdb_id, media_type)
        return _ok(d)
    except Exception as e:
        return _err(e)


# ---------------- 整理（Plan → 确认 → Execute） ----------------

@server.tool(description="【只读】扫描散乱目录生成整理方案 Plan（不改任何文件）。"
                         "source 如 /115/云下载；target_root 省略则按媒体类型自动选库。"
                         "media_type: movie/tv/auto。"
                         "include_containers=true 时下钻「合集/专辑/（系列）」内部；"
                         "drain_inbox=true（默认）时把收件箱 0-待整理 里的作品一并搬走；"
                         "normalize_names=true（默认）时纠正明确违规的存量名"
                         "（旧式 {tmdb-N} 标识 → {tmdbid-N}；文件名里的 ID 与方括号标签）。"
                         "strict=true 为严格归一：目录强制带 {tmdbid-N}、季目录强制 Season 01、"
                         "已就位的英文名/简化名文件也按规范模板改名（放弃「少改名」宽容）。"
                         "返回方案摘要与 plan_id。",
             annotations=A_PLAN)
def build_plan(source: str, target_root: str = "", media_type: str = "auto",
               include_containers: bool = False, drain_inbox: bool = True,
               normalize_names: bool = True, strict: bool = False) -> Result:
    try:
        plan = planner.build_plan(source, target_root or None, media_type,
                                  include_containers=include_containers,
                                  drain_inbox=drain_inbox,
                                  normalize_names=normalize_names,
                                  strict=strict)
        planner.save_plan(plan)
        s = plan["summary"]
        lines = [f"Plan {plan['plan_id']}（已保存，未执行 —— 需要你确认后才会动网盘）",
                 f"作品组 {s['groups']} 个 | 媒体文件 {s['media_files']} 个",
                 f"新建目录 {s['mkdirs']} | 整目录搬移 {s.get('dir_moves', 0)} | 文件移动批次 {s['moves']} "
                 f"| 改名 {s['renames']} | 已就位跳过 {s['already_ok']}"]
        if s.get("skipped"):
            lines.append(f"ℹ️ {s['skipped']} 个文件保持原位（非媒体/容器）")
        if plan["unmatched"]:
            lines.append(f"⚠️ 未匹配 {len(plan['unmatched'])} 项（需人工确认标题/年份）: " +
                         "; ".join(u["guess_title"] + f" ({u['reason']})" for u in plan["unmatched"][:5]))
        for g in plan["groups"]:
            lines.append(f"  [{g['kind']}] {g['title']} ({g['year']}) tmdb={g['tmdb_id'] or '未匹配'} → {g['target_path']}")
            if g.get("dir_move_only"):
                lines.append(f"    （目录名已合规，整体搬移，内部 {len(g['files'])} 个文件不改名）")
                continue
            for f in g["files"][:6]:
                mark = "= 保持不变" if f.get("op") == "skip-same" or f["new_name"] == f["name"] else f"→ {f['new_name']}"
                lines.append(f"    {f['name']} {mark}")
            if len(g["files"]) > 6:
                lines.append(f"    ...共 {len(g['files'])} 个文件")
        return _ok({"plan_id": plan["plan_id"], "summary": s,
                    "detail": "\n".join(lines)})
    except Exception as e:
        traceback.print_exc()
        return _err(e)


@server.tool(description="查看已生成的 Plan 详情（含全部动作）。",
             annotations=A_READONLY)
def preview_plan(plan_id: str) -> Result:
    try:
        plan = planner.load_plan(plan_id)
        return _ok({"status": plan["status"], "source": plan["source"],
                    "target_root": plan["target_root"], "summary": plan["summary"],
                    "groups": [{"title": g["title"], "year": g["year"], "kind": g["kind"],
                                "target_path": g["target_path"],
                                "files": g["files"]} for g in plan["groups"]],
                    "actions": plan["actions"]})
    except Exception as e:
        return _err(e)


@server.tool(description="【危险】执行整理 Plan。必须先向用户展示 preview_plan 结果并获得明确确认，"
                         "用户同意后才能传 confirm=true。默认 confirm=false 只做预检。",
             annotations=A_EXECUTE)
def execute_plan(plan_id: str, confirm: bool = False) -> Result:
    try:
        plan = planner.load_plan(plan_id)
        result = executor.execute(plan, confirm=confirm)
        if confirm:
            planner.update_plan(plan)
        return _ok(result)
    except Exception as e:
        return _err(e)


# ---------------- 刮削 ----------------

@server.tool(description="刮削作品目录：下载 TMDB 海报/背景/logo + 生成 NFO 上传。"
                         "命名遵循规范 —— 电影用前缀式（{主文件主体}-poster.jpg，nfo 与主文件同名），"
                         "剧集用无前缀式（poster.jpg / clearlogo.png / tvshow.nfo）。"
                         "work_dir 如 /115/01-电影/沙丘2 (2024) {tmdbid-693134}。"
                         "cleanup_legacy=true 时删掉电影目录里旧式无前缀图片，完成形态归一。",
             annotations=A_SCRAPE)
def scrape_dir(work_dir: str, media_type: str = "auto", tmdb_id: str = "",
               force: bool = False, cleanup_legacy: bool = False) -> Result:
    try:
        result = scraper.scrape(work_dir, media_type, tmdb_id, force, cleanup_legacy)
        return _ok(result)
    except Exception as e:
        traceback.print_exc()
        return _err(e)


# ---------------- 审计 ----------------

@server.tool(description="【只读】审计网盘目录与命名规范的偏差，输出整改清单。"
                         "root 如 /115/01-电影（会下钻合集/专辑/（系列））。"
                         "media_type: movie/tv/auto。报告包含问题码、详情与修改建议。",
             annotations=A_READONLY)
def audit_library(root: str, media_type: str = "auto",
                  include_containers: bool = True) -> Result:
    try:
        result = auditor.audit(root, media_type, include_containers)
        s = result["summary"]
        lines = [f"审计 {root}：作品 {s['works']} 个，合规 {s['ok']} 个，"
                 f"有偏差 {s['nonconforming']} 个（error {s['errors']} / warn {s['warns']}）"]
        if result["by_code"]:
            lines.append("问题分布：" + "，".join(
                f"{k}×{v}" for k, v in sorted(result["by_code"].items(),
                                              key=lambda kv: -kv[1])))
        for w in result["issues"][:40]:
            lines.append(f"\n[{w['kind']}] {w['path']}")
            for it in w["issues"][:6]:
                lines.append(f"  ({it['level']}) {it['code']}: {it['detail']}"
                             + (f" → {it['suggestion']}" if it["suggestion"] else ""))
        if len(result["issues"]) > 40:
            lines.append(f"\n...共 {len(result['issues'])} 个有偏差的作品目录，"
                         f"完整清单见结构化数据")
        return _ok({"summary": s, "by_code": result["by_code"],
                    "issues": result["issues"], "detail": "\n".join(lines)})
    except Exception as e:
        traceback.print_exc()
        return _err(e)


# ---------------- 运维 ----------------

@server.tool(description="健康检查：配置完整性 + OpenList 连通性 + TMDB 可用性 + 挂载根目录。"
                         "首次使用先跑这个：issues 会给出逐项配置指引。",
             annotations=A_READONLY)
def health_check() -> Result:
    issues = []
    hint_env = "在 MCP 配置（如 ~/.workbuddy/mcp.json → aix8-pan → env）填写："
    top: list = []
    ol, tm = _cfg["openlist"], _cfg["tmdb"]

    # 分阶段引导：地址 → 账号密码 → 连通性
    if not ol.get("base_url"):
        issues.append("OpenList: 未配置服务地址（OPENLIST_URL）。"
                      "需先部署 OpenList 并挂载 115 网盘（参考 github.com/OpenListTeam/OpenList），"
                      "再回来配置地址")
    elif not ol.get("username") or not ol.get("password"):
        missing = "、".join(n for n, v in (("OPENLIST_USER", ol.get("username")),
                                           ("OPENLIST_PASS", ol.get("password"))) if not v)
        issues.append(f"OpenList: 未配置账号凭据（{missing}）。{hint_env} {missing}")
    else:
        try:
            items = client.list_dir("/115", refresh=False)
            top = [i["name"] for i in items if i.get("is_dir")][:10]
        except Exception as e:
            issues.append(f"OpenList: {e}（若为登录失败请核对 OPENLIST_USER/OPENLIST_PASS；"
                          f"若连不上请检查 OPENLIST_URL 服务是否在线）")

    if not tm.get("api_key"):
        issues.append(f"TMDB: 未配置 API Key（TMDB_API_KEY）。{hint_env} TMDB_API_KEY")
    elif not tm.get("api_host"):
        issues.append(f"TMDB: 未配置 API 地址（TMDB_HOST）。{hint_env} TMDB_HOST")
    else:
        try:
            tmdb.search("test", "", "movie")
        except Exception as e:
            issues.append(f"TMDB: {e}（key 失效请更换 TMDB_API_KEY；"
                          f"连不上请检查 TMDB_HOST，可用官方 api.themoviedb.org 或自建代理）")
    return _ok({"ok": len(issues) == 0, "issues": issues, "root_dirs": top})


async def _main():
    await server.run_stdio_async()


def main() -> None:
    """Console entry（pyproject.toml → aix8-pan 命令）。"""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
