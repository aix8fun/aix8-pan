"""端到端写入测试（在网盘临时沙盒内执行，结束自动清理）

覆盖：mkdir / move_dir / move / rename / upload(刮削) / cleanup_empty_dir
沙盒根：/115/AA-TODO/.panbutler-e2e    —— 测试结束整个删除，不触碰用户媒体库
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.config import load_config
from aix8pan.executor import Executor
from aix8pan.openlist import OpenListClient
from aix8pan.planner import Planner
from aix8pan.scraper import Scraper

SANDBOX = "/115/AA-TODO/.panbutler-e2e"
INBOX = f"{SANDBOX}/inbox"
TVINBOX = f"{SANDBOX}/tvinbox"
LIB = f"{SANDBOX}/library"


def main():
    cfg = load_config()
    ol = cfg["openlist"]
    c = OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
    planner = Planner(cfg, c)
    executor = Executor(cfg, c)
    scraper = Scraper(cfg, c)
    fails = []

    def check(cond, msg):
        print(("  PASS " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    try:
        # 0. 准备沙盒
        print("[0] 准备沙盒")
        c.ensure_dir(INBOX)
        c.ensure_dir(TVINBOX)
        c.ensure_dir(LIB)
        c.upload(f"{INBOX}/沙丘2.2024.2160p.WEB-DL.H265.DDP5.1.mkv", b"fake-mkv-content" * 100)
        c.upload(f"{INBOX}/沙丘2.2024.2160p.WEB-DL.H265.DDP5.1.nfo", b"<movie/>")
        c.upload(f"{INBOX}/readme.txt", b"non-media companion")
        for ep in (1, 2, 3):
            c.upload(f"{TVINBOX}/Dune.Prophecy.S01E0{ep}.1080p.WEB-DL.H264.mkv",
                     b"fake-tv" * 50)
        items = c.list_all(SANDBOX, refresh=True)
        check(len(items) >= 2, f"沙盒已建立（{len(items)} 个子目录）")

        # 1. 规划（只读）
        print("[1] 规划（只读）")
        plan = planner.build_plan(INBOX, target_root=LIB, media_type="movie")
        planner.save_plan(plan)
        s = plan["summary"]
        print("   summary:", json.dumps(s, ensure_ascii=False))
        check(s["media_files"] == 1, "识别到 1 个媒体文件")
        check(s["mkdirs"] + s["dir_moves"] + s["moves"] + s["renames"] > 0, "产生了动作")
        g = plan["groups"][0]
        print(f"   标题={g['title']} 年份={g['year']} tmdb={g['tmdb_id']} → {g['target_path']}")
        check(g["tmdb_id"] != "", "TMDB 匹配到 ID")
        check(Path(g["target_path"]).name.startswith("沙丘2 (2024)"), "目标目录名符合规范")
        new_media = [f["new_name"] for f in g["files"] if f["kind"] == "media"][0]
        check("沙丘2" in new_media and "(2024)" in new_media and "2160p" in new_media,
              f"目标文件名符合规范: {new_media}")
        # 执行前确认目标目录尚不存在（证明未提前改动）
        before = {e["name"] for e in c.list_all(LIB, refresh=True)}
        check(not before, f"执行前库为空（未提前改动）: {before}")

        # 2. 预检（confirm=False 不应改动）
        print("[2] 预检 dry-run")
        pre = executor.execute(plan, confirm=False)
        check(pre.get("precheck") is True, "未确认时返回预检而不执行")
        after_dry = {e["name"] for e in c.list_all(LIB, refresh=True)}
        check(after_dry == before, "dry-run 未产生任何改动")

        # 3. 执行
        print("[3] 执行 Plan")
        res = executor.execute(plan, confirm=True)
        planner.update_plan(plan)
        print("   执行结果:", json.dumps(res, ensure_ascii=False)[:300])
        check(res["failed"] == 0, f"全部动作成功（done={res['done']}）")

        # 4. 校验结果
        print("[4] 校验落地结果")
        lib_items = c.list_all(LIB, refresh=True)
        names = [i["name"] for i in lib_items]
        check(len(names) == 1, f"库内恰好 1 个作品目录: {names}")
        work_dir = f"{LIB}/{names[0]}"
        files = [i["name"] for i in c.list_all(work_dir, refresh=True)]
        print("   作品目录内容:", files)
        check(any(n.endswith(".mkv") and "沙丘2" in n and "(2024)" in n for n in files),
              "媒体文件已按规范改名")
        check(any(n.endswith(".nfo") and "沙丘2" in n and "Dune" in n for n in files),
              "nfo 已随主文件改名")
        # 网盘目录有最终一致性：稍等再强刷校验
        import time as _t
        inbox_left = []
        for _ in range(6):
            _t.sleep(0.8)
            try:
                inbox_left = c.list_all(INBOX, refresh=True)
            except Exception:
                inbox_left = []          # 目录已不存在（整目录被搬走）→ 视为无剩余
            if inbox_left:
                break
        left_names = [i["name"] for i in inbox_left]
        check(left_names == ["readme.txt"], f"未知类型文件安全留在原位（剩余={left_names}）")

        # 5. 幂等复跑
        print("[5] 幂等复跑（对结果再规划一次，应零动作）")
        plan2 = planner.build_plan(LIB, target_root=LIB, media_type="movie")
        s2 = plan2["summary"]
        print("   summary:", json.dumps(s2, ensure_ascii=False))
        acts = [a for a in plan2["actions"] if a["action"] != "mkdir"]
        check(not acts, f"复跑无改动动作（{len(acts)} 个）: {[a['action'] for a in acts][:3]}")

        # 6. 剧集：搬 + 改名 + Season 目录
        print("[6] 剧集整理")
        plan3 = planner.build_plan(TVINBOX, target_root=LIB, media_type="tv")
        planner.save_plan(plan3)
        print("   summary:", json.dumps(plan3["summary"], ensure_ascii=False))
        res3 = executor.execute(plan3, confirm=True)
        planner.update_plan(plan3)
        check(res3["failed"] == 0, f"剧集动作全成功（done={res3['done']}）")
        tv_items = [i["name"] for i in c.list_all(LIB, refresh=True)]
        tv_dir = next((n for n in tv_items if "沙丘" in n and n != names[0]), None)
        print("   库内目录:", tv_items)
        check(tv_dir is not None, "剧集目录已落库")
        if tv_dir:
            seasons = [i["name"] for i in c.list_all(f"{LIB}/{tv_dir}", refresh=True)]
            print("   剧集目录内容:", seasons)
            check(any(s.lower().startswith("season") for s in seasons), "生成了 Season 目录")
            sdir = next(s for s in seasons if s.lower().startswith("season"))
            eps = [i["name"] for i in c.list_all(f"{LIB}/{tv_dir}/{sdir}", refresh=True)]
            print("   剧集文件:", eps)
            check(len(eps) == 3, f"3 集全部就位（{len(eps)}）")
            check(all("S01E" in e for e in eps), "集号令牌正确")

        # 7. 刮削（真实下载 TMDB 图片 + 上传 + nfo，命名按规范：电影用前缀式）
        print("[7] 刮削")
        sc = scraper.scrape(work_dir, media_type="movie", force=True)
        print("   刮削结果:", json.dumps(sc, ensure_ascii=False)[:400])
        check(sc.get("ok") is True, "刮削执行成功")
        stem = sc.get("media_stem") or ""
        check(stem.startswith("沙丘2 ") and "(2024)" in stem,
              f"artwork 前缀 = 主文件主体（{stem}）")
        check(f"{stem}-poster.jpg" in sc.get("uploaded", []),
              f"前缀式海报已上传（{stem}-poster.jpg）")
        check(f"{stem}-clearlogo.png" in sc.get("uploaded", []),
              "clearlogo.png 命名（不是 logo.png）")
        check(f"{stem}.nfo" in sc.get("uploaded", []),
              "nfo 与主文件同名")
        files2 = [i["name"] for i in c.list_all(work_dir, refresh=True)]
        poster = next((i for i in c.list_all(work_dir, refresh=True)
                       if i["name"] == f"{stem}-poster.jpg"), None)
        check(poster is not None and (poster.get("size") or 0) > 5000,
              f"海报是真实图片（{poster and poster.get('size')} 字节）")
        check(not any(n in ("poster.jpg", "logo.png", "movie.nfo") for n in files2),
              f"未产生无前缀旧式产物（{files2}）")
        print("   作品目录:", files2)
        # 再刮一次应全部跳过（不重复上传）
        sc2 = scraper.scrape(work_dir, media_type="movie")
        check(len(sc2.get("uploaded", [])) == 0, f"重复刮削不重复上传（uploaded={sc2.get('uploaded')}）")

        # 8. 审计器（只读，应报告 0 偏差）
        print("[8] 审计（只读）")
        from aix8pan.auditor import Auditor
        au = Auditor(cfg, c).audit(LIB, media_type="auto")
        print("   ", json.dumps(au["summary"], ensure_ascii=False))
        print("    问题分布:", au["by_code"])
        check(au["summary"]["errors"] == 0,
              f"导出结果零 error（{[i['code'] for w in au['issues'] for i in w['issues']][:5]}）")

    finally:
        print("[9] 清理沙盒")
        try:
            c.remove("/115/AA-TODO", [".panbutler-e2e"])
            left = [i["name"] for i in c.list_all("/115/AA-TODO", refresh=True)]
            print("   AA-TODO 剩余:", left)
        except Exception as ex:
            print("   清理失败:", ex)

    print()
    print("全部通过 ✅" if not fails else f"失败 {len(fails)} 项 ❌\n - " + "\n - ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
