"""MCP 服务契约测试（无网络）

守门两件事：
  1. 全部工具都发布 outputSchema（结构化输出）+ ToolAnnotations（权限提示）——
     回归目标：宿主永远能拿到 structuredContent，而不是只能解析文本 JSON。
  2. 统一信封 Result 的形状：成功 {ok: True, data} / 失败 {ok: False, error}，
     且 data 一定是合法 JSON（datetime/Path 等被兜底成 str）。

用法：python3 tests/test_server_contract.py
"""
import asyncio
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan import server as srv  # noqa: E402

EXPECTED_TOOLS = {
    "list_dir", "search_files", "get_paths", "get_download_url",
    "parse_name", "naming_spec_tool", "tmdb_search", "tmdb_detail",
    "build_plan", "preview_plan", "execute_plan",
    "scrape_dir", "audit_library", "health_check",
}
# 写网盘的工具：annotations 上必须标 destructive
DESTRUCTIVE_TOOLS = {"execute_plan", "scrape_dir"}
# 只读工具（build_plan 写本地方案文件，不算只读）
READONLY_TOOLS = EXPECTED_TOOLS - DESTRUCTIVE_TOOLS - {"build_plan"}


def _run(coro):
    return asyncio.run(coro)


def test_all_tools_registered():
    tools = _run(srv.server.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS, f"工具集漂移：多 {names - EXPECTED_TOOLS} 少 {EXPECTED_TOOLS - names}"


def test_output_schema_published():
    tools = _run(srv.server.list_tools())
    for t in tools:
        s = getattr(t, "output_schema", None)
        assert s, f"{t.name} 未发布 outputSchema（返回注解应为 Result TypedDict）"
        assert s.get("type") == "object", f"{t.name} outputSchema 根应为 object: {s}"
        assert "ok" in (s.get("required") or []), f"{t.name} outputSchema 缺 required ok: {s}"
        props = s.get("properties") or {}
        assert "data" in props and "error" in props, f"{t.name} 信封缺 data/error: {props}"


def test_annotations_present():
    tools = _run(srv.server.list_tools())
    for t in tools:
        a = t.annotations
        assert a is not None, f"{t.name} 缺 ToolAnnotations"
        if t.name in DESTRUCTIVE_TOOLS:
            assert a.destructive_hint is True and a.read_only_hint is False, t.name
        elif t.name in READONLY_TOOLS:
            assert a.read_only_hint is True and a.destructive_hint is False, t.name


def _convert(tool_name: str, **args):
    """直接调工具函数并走 SDK 的结果转换（与线上调用同一条路径）。"""
    tool = srv.server._tool_manager._tools[tool_name]
    return tool.fn_metadata.convert_result(tool.fn(**args))


def test_structured_content_offline_tools():
    # 纯本地工具（不碰网盘/TMDB）：结构化内容 + 文本通道都要有
    res = _convert("get_paths")
    assert res.structured_content["ok"] is True
    assert res.content and res.content[0].type == "text", "文本通道必须保留（向后兼容）"
    res = _convert("parse_name", name="沙丘2 (2024) {tmdbid-693134}", is_dir=True)
    sc = res.structured_content
    assert sc["ok"] is True and sc["data"]["tmdb_id"] == "693134", sc
    res = _convert("naming_spec_tool")
    assert res.structured_content["data"]["version"] == srv.naming_spec.SPEC_VERSION


def test_error_envelope():
    res = _convert("preview_plan", plan_id="plan-不存在的-id")
    sc = res.structured_content
    assert sc["ok"] is False and isinstance(sc["error"], str) and sc["error"], sc
    assert "data" not in sc, "失败信封不得带 data"


def test_jsonable_fallback():
    data = srv._jsonable({"when": datetime.datetime(2026, 10, 8, 12, 0),
                          "p": Path("/tmp/x"), "ok": 1})
    assert isinstance(data["when"], str) and isinstance(data["p"], str)
    assert data["ok"] == 1


ENV_KEYS = ("OPENLIST_URL", "OPENLIST_USER", "OPENLIST_PASS", "TMDB_HOST", "TMDB_API_KEY")


def test_credential_env_override():
    """分发型配置契约：OPENLIST_*/TMDB_* 环境变量 > config.json > 默认值；
    config.json 本体不得存明文凭据；默认命名模板必须来自事实源。"""
    import json
    import os
    import tempfile

    # ① config.json 不含凭据字段
    raw = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text("utf-8"))
    assert "password" not in raw.get("openlist", {}), "config.json 不得存放 openlist.password"
    assert "api_key" not in raw.get("tmdb", {}), "config.json 不得存放 tmdb.api_key"

    # ② 全新用户（空 config + 无 env）：凭据空但不崩溃，命名模板来自事实源
    from aix8pan.config import load_config
    saved = {k: os.environ.get(k, "") for k in ENV_KEYS}
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write("{}")
        tmp = f.name
    try:
        fresh = load_config(tmp)
        assert fresh["openlist"]["base_url"] == "" and fresh["tmdb"]["api_key"] == ""
        assert fresh["naming"]["movie_file_template"] == "{title} {original} ({year}) [{tech}]"

        # ③ env 覆盖文件值；env 为空回落文件值；TMDB_HOST 双供 api/image host
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"openlist": {"base_url": "from-file-url", "password": "from-file-pwd"},
                       "tmdb": {"api_key": "from-file-key"}}, f)
        os.environ.update({"OPENLIST_URL": "from-env-url", "OPENLIST_PASS": "from-env-pwd",
                           "TMDB_HOST": "from-env-host"})
        cfg = load_config(tmp)
        assert cfg["openlist"]["base_url"] == "from-env-url", "env 应覆盖文件"
        assert cfg["openlist"]["password"] == "from-env-pwd", "env 应覆盖文件"
        assert cfg["tmdb"]["api_key"] == "from-file-key", "env 为空应回落文件"
        assert cfg["tmdb"]["api_host"] == "from-env-host" and cfg["tmdb"]["image_host"] == "from-env-host", \
            "TMDB_HOST 应同时供给 api_host 与 image_host"
    finally:
        for k, v in saved.items():
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        Path(tmp).unlink(missing_ok=True)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
