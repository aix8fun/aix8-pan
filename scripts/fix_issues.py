"""修正「合集 / 专辑」里 5 处命名偏差 + 补齐缺失海报。

来源：`合集_专辑_作品规范核对表.xlsx` 的问题清单。

用法：
    python scripts/fix_issues.py            # 只读：生成 Plan 并打印预览
    python scripts/fix_issues.py --execute  # 执行（Plan → 执行 → 复验 → 刮削）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.executor import Executor
from aix8pan.planner import Planner
from aix8pan.scraper import Scraper

MOV = "/115/01-电影"
SPIDEY_ROOT = f"{MOV}/合集/漫威宇宙（主线）/蜘蛛侠（复仇者联盟）（系列）"

# ── 5 处改名（source 为作品目录本身；target_root 为其父容器）──────────
RENAMES = [
    {
        "label": "碟中谍6：去掉多余的版本修饰词「- IMAX」",
        "source": f"{MOV}/合集/碟中谍（系列）/碟中谍6：全面瓦解 - IMAX (2018) {{tmdbid-353081}}",
        "target_root": f"{MOV}/合集/碟中谍（系列）",
        "title_override": "",
    },
    {
        "label": "007之太空城 → 007：太空城（对齐 TMDB 与系列内其余 25 部）",
        "source": f"{MOV}/合集/007（系列）/007之太空城 (1979) {{tmdbid-698}}",
        "target_root": f"{MOV}/合集/007（系列）",
        "title_override": "",
    },
    {
        "label": "Spider-Man - No Way Home → 蜘蛛侠：英雄无归",
        "source": f"{SPIDEY_ROOT}/Spider-Man - No Way Home (2021) {{tmdbid-634649}}",
        "target_root": SPIDEY_ROOT,
        "title_override": "蜘蛛侠：英雄无归",
    },
    {
        "label": "Black Widow → 黑寡妇",
        "source": f"{MOV}/专辑/Black Widow (2021) {{tmdbid-497698}}",
        "target_root": f"{MOV}/专辑",
        "title_override": "黑寡妇",
    },
    {
        "label": "变形金刚：超能勇士崛起 补 {tmdbid-667538} 标识",
        "source": f"{MOV}/专辑/变形金刚：超能勇士崛起 (2023)",
        "target_root": f"{MOV}/专辑",
        "title_override": "",
    },
]

# ── 刮削：补缺失海报 ─────────────────────────────────────────────
# 注：蜘蛛侠 / 黑寡妇 目录改名后，nfo 里的 <title> 仍是英文 —— **刻意不刷新**：
#     ① 库内 nfo 是 tMM 富信息版（含完整 cast/crew，26–33 KB），本工具生成的是
#        精简版（~1 KB），覆盖属信息降级；
#     ② 全库 nfo 都是 tMM 英文标题风格，单独改这两个反而破坏一致性。
SCRAPES = [
    {
        "label": "战狼 (2015)：补缺失的 poster",
        "work_dir": f"{MOV}/合集/战狼（系列）/战狼 (2015) {{tmdbid-335462}}",
        "tmdb_id": "335462",
        "title_override": "",
        "force_nfo": False,
    },
]


def build_all() -> list[dict]:
    """为每个待改作品生成 Plan。源目录已不存在（已改过）→ 跳过，保证可重复运行。"""
    planner = Planner()
    out = []
    for item in RENAMES:
        if not planner.client.exists(item["source"]):
            print(f"⤵ 跳过（源目录已不存在，视为已完成）：{item['label']}")
            continue
        plan = planner.build_plan(
            item["source"], target_root=item["target_root"], media_type="movie",
            canonical_folder=True, title_override=item["title_override"],
            use_tmdb_title=True)
        planner.save_plan(plan)
        out.append({"item": item, "plan": plan})
    return out


def preview(built: list[dict]) -> None:
    for b in built:
        item, plan = b["item"], b["plan"]
        print(f"\n{'=' * 78}\n■ {item['label']}")
        print(f"  源   : {item['source']}")
        acts: dict[str, int] = {}
        for a in plan["actions"]:
            acts[a["action"]] = acts.get(a["action"], 0) + 1
        print(f"  Plan : {plan['plan_id']} | 动作 {acts or '（无）'}")
        for g in plan["groups"]:
            print(f"  作品 : {g['title']} ({g['year']}) tmdb={g['tmdb_id']}")
            print(f"  目录 : {g['source_dir'].split('/')[-1]}")
            print(f"       → {g['target_path'].split('/')[-1]}")
            if g.get("dir_move_only"):
                print("       （仅目录改名，内部文件不动）")
                continue
            for f in g["files"]:
                mark = "  = 不变" if f["new_name"] == f["name"] else ""
                print(f"       {f['name']}")
                if mark:
                    print(f"         {mark}")
                else:
                    print(f"         → {f['new_name']}")
        if plan["unmatched"]:
            print("  ⚠ 未匹配:", plan["unmatched"])


def execute(built: list[dict]) -> bool:
    ok = True
    ex = Executor()
    planner = Planner()
    for b in built:
        item, plan = b["item"], b["plan"]
        print(f"\n▶ 执行：{item['label']}")
        if not plan["actions"]:
            print("   无动作，跳过")
            continue
        res = ex.execute(plan, confirm=True)
        print(f"   完成 {res['done']} / 失败 {res['failed']}")
        for e in res.get("errors") or []:
            print("   ✗", e)
        ok = ok and res["failed"] == 0
        planner.update_plan(plan)
    return ok


def scrape_all() -> None:
    sc = Scraper()
    for item in SCRAPES:
        print(f"\n▶ 刮削：{item['label']}")
        if not sc.client.exists(item["work_dir"]):
            print("   ⤵ 目录不存在，跳过")
            continue
        try:
            r = sc.scrape(item["work_dir"], media_type="movie", tmdb_id=item["tmdb_id"],
                          title_override=item["title_override"],
                          force_nfo=item["force_nfo"])
            print("   ", json.dumps(r, ensure_ascii=False))
        except Exception as ex:
            print(f"    ✗ 失败: {ex}")


def verify(built: list[dict]) -> None:
    from aix8pan.config import load_config
    from aix8pan.openlist import OpenListClient
    cfg = load_config()
    ol = cfg["openlist"]
    c = OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
    print(f"\n{'=' * 78}\n■ 复验")
    print("—— 改名后：父目录中已无旧名、已出现新名 ——")
    for b in built:
        item, plan = b["item"], b["plan"]
        parent = item["source"].rsplit("/", 1)[0]
        src_name = item["source"].rsplit("/", 1)[1]
        want = plan["groups"][0]["target_path"].rsplit("/", 1)[1]
        names = [e["name"] for e in c.list_all(parent, refresh=True)]
        print(f"  {parent}")
        print(f"    旧名仍在? {'✗ 是' if src_name in names else '✓ 否'}")
        print(f"    新名出现? {'✓ 是' if want in names else '✗ 否'}   {want}")
    print("—— 刮削后：作品目录文件清单 ——")
    for item in SCRAPES:
        wd = item["work_dir"]
        try:
            files = [e["name"] for e in c.list_all(wd, refresh=True)]
        except Exception as ex:
            print(f"  {wd}\n    ✗ 读取失败 {ex}")
            continue
        print(f"  {wd.rsplit('/', 1)[1]}")
        for f in files:
            print(f"      {f}")


def main() -> int:
    do_exec = "--execute" in sys.argv
    built = build_all()
    preview(built)
    if not do_exec:
        print("\n\n（只读预览。加 --execute 才执行）")
        return 0
    if not execute(built):
        print("\n✗ 有动作失败，停止后续步骤")
        return 1
    scrape_all()
    verify(built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
