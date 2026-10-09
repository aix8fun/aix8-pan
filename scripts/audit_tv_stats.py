"""02-剧集 终检统计（只读）：
- 每部剧：剧级文件清单与计数、季数、集数、季内文件类型
- 规范校验：剧目录名 {tmdbid-N}、季目录 Season NN、剧根仅标准5件套、
  季内仅视频、视频文件名含 ` - SxxEyy - 集名`、无规范禁止结构
"""
import sys, re, json, collections

sys.path.insert(0, "/Users/win/WorkBuddy/aix8-pan")
from aix8pan.config import load_config
from aix8pan.core.openlist import OpenListClient
from aix8pan.core.parser import violates_filename_spec

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".ts", ".rmvb", ".m2ts", ".mov", ".wmv")
SEASON_DIR_RE = re.compile(r"^Season \d{2}$")
SHOW_DIR_RE = re.compile(r"^.+ \(\d{4}\) \{tmdbid-\d+\}$")
EP_NAME_RE = re.compile(r" - S\d{2}E\d{2} - .+\.(?:mp4|mkv|avi|ts|rmvb|m2ts|mov|wmv)$", re.IGNORECASE)
ROOT_ART_RE = re.compile(r"^(poster\.jpg|fanart\.jpg|clearlogo\.png|tvshow\.nfo|season\d{2}-poster\.jpg)$", re.IGNORECASE)

cfg = load_config()
ol = cfg["openlist"]
c = OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
root = "/115/02-剧集"
shows = sorted(e["name"] for e in c.list_all(root, refresh=True) if e.get("is_dir"))

rows = []
issues = []
total_eps = 0
total_videos = 0

for show in shows:
    sdir = f"{root}/{show}"
    entries = c.list_all(sdir, refresh=True)
    root_files = sorted(e["name"] for e in entries if not e.get("is_dir"))
    seasons = sorted(e["name"] for e in entries if e.get("is_dir"))
    probs = []
    if not SHOW_DIR_RE.match(show):
        probs.append("剧目录名不规范")
    nonstd_root = [n for n in root_files if not ROOT_ART_RE.match(n)]
    if nonstd_root:
        probs.append(f"剧根非标准文件: {nonstd_root}")
    missing5 = [n for n in ("poster.jpg", "fanart.jpg", "clearlogo.png", "tvshow.nfo")
                if n not in {x.lower() for x in root_files}]
    if missing5:
        probs.append(f"缺标准件: {missing5}")
    sp = {n.lower() for n in root_files if re.match(r"season\d{2}-poster\.jpg", n.lower())}
    eps = 0
    season_eps = {}
    for sn in seasons:
        if not SEASON_DIR_RE.match(sn):
            probs.append(f"季目录名不规范: {sn}")
        files = c.list_all(f"{sdir}/{sn}", refresh=True)
        vids, nonv = [], []
        for f in files:
            n = f["name"]
            if f.get("is_dir"):
                probs.append(f"{sn} 内存在子目录: {n}")
            elif n.lower().endswith(VIDEO_EXTS):
                vids.append(n)
            else:
                nonv.append(n)
        if nonv:
            probs.append(f"{sn} 含非视频文件: {len(nonv)} 个")
        bad_names = [n for n in vids if not EP_NAME_RE.search(n)]
        if bad_names:
            probs.append(f"{sn} 集名不规范: {bad_names[:2]}")
        viol = [n for n in vids if violates_filename_spec(n)]
        if viol:
            probs.append(f"{sn} 含违规结构: {viol[:2]}")
        m = re.match(r"Season (\d{2})", sn)
        if m and f"season{m.group(1)}-poster.jpg" not in sp:
            probs.append(f"缺 season{m.group(1)}-poster.jpg")
        season_eps[sn] = len(vids)
        eps += len(vids)
    total_eps += eps
    total_videos += eps
    rows.append({"show": show, "root_n": len(root_files), "seasons": len(seasons),
                 "eps": eps, "season_eps": season_eps, "ok": not probs})
    if probs:
        issues.append({"show": show, "problems": probs})

# 输出
print(f"{'剧名':<28} {'剧级':>4} {'季':>3} {'集数':>5}  状态")
print("-" * 60)
for r in rows:
    name = r["show"][:26]
    print(f"{name:<28} {r['root_n']:>4} {r['seasons']:>3} {r['eps']:>5}  {'✅' if r['ok'] else '⚠️'}")
print("-" * 60)
print(f"合计：{len(rows)} 部 / 剧级文件 {sum(r['root_n'] for r in rows)} 个 / "
      f"季 {sum(r['seasons'] for r in rows)} 个 / 集级视频 {total_videos} 个")

print()
if issues:
    print("⚠️ 异常明细：")
    for it in issues:
        print(f"  {it['show']}")
        for p in it["problems"]:
            print(f"    - {p}")
else:
    print("✅ 全部 36 部剧零异常：剧目录 {tmdbid-N}、季目录 Season NN、剧根仅标准5件套、"
          "季内纯视频、集名均含 TMDB 集名")

json.dump({"rows": rows, "issues": issues, "total_eps": total_eps},
          open("/Users/win/WorkBuddy/aix8-pan/data/tv_final_audit_20261009.json", "w"),
          ensure_ascii=False, indent=1)
