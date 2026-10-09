"""全库健康体检（只读）：扫 01-电影 / 03-动画 / 04-纪录片 / 12-乡村剧
每个库：目录形态（是否规范 目录名）、明显非规范季目录/文件、异常文件。
"""
import sys, re

sys.path.insert(0, "/Users/win/WorkBuddy/aix8-pan")
from aix8pan.config import load_config
from aix8pan.core.openlist import OpenListClient

SHOW_DIR_RE = re.compile(r"^.+ \(\d{4}\) \{tmdbid-\d+\}$")
SEASON_RE = re.compile(r"^Season \d{2}$")
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".ts", ".rmvb", ".m2ts", ".mov", ".wmv", ".iso", ".mpg", ".strm")

cfg = load_config()
ol = cfg["openlist"]
c = OpenListClient(ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])

for label, path in [("电影", "/115/01-电影"), ("动画", "/115/03-动画"),
                    ("纪录片", "/115/04-纪录片"), ("乡村剧", "/115/12-乡村剧")]:
    print(f"\n{'='*66}\n■ {label} {path}\n{'='*66}")
    try:
        entries = c.list_all(path, refresh=True)
    except Exception as ex:
        print(f"  !! 无法列出: {ex}")
        continue
    dirs = [e["name"] for e in entries if e.get("is_dir")]
    files = [e["name"] for e in entries if not e.get("is_dir")]
    print(f"  顶层: {len(dirs)} 目录 / {len(files)} 文件")
    bad_dirs = [d for d in dirs if not SHOW_DIR_RE.match(d)]
    print(f"  非规范目录名: {len(bad_dirs)}")
    for d in bad_dirs[:20]:
        print(f"    - {d}")
    if files:
        print(f"  顶层散文件: {files[:10]}")
    # 抽查每个规范目录的内部形态（只列一层，不递归，控制耗时）
    issues = 0
    for d in dirs:
        try:
            sub = c.list_all(f"{path}/{d}", refresh=True)
        except Exception as ex:
            print(f"    !! {d}: {ex}")
            issues += 1
            continue
        subdirs = [x["name"] for x in sub if x.get("is_dir")]
        subfiles = [x["name"] for x in sub if not x.get("is_dir")]
        bad_seasons = [s for s in subdirs if "eason" in s or s.startswith(("S", "第")) or "季" in s]
        bad_seasons = [s for s in bad_seasons if not SEASON_RE.match(s)]
        nonvid = [f for f in subfiles if not f.lower().endswith(VIDEO_EXTS)
                  and not f.lower().endswith((".jpg", ".png", ".nfo", ".srt", ".ass", ".txt", ".url"))]
        if bad_seasons or nonvid:
            issues += 1
            print(f"    ⚠️ {d}:")
            for s in bad_seasons[:5]:
                print(f"       季目录名: {s}")
            for f in nonvid[:5]:
                print(f"       异常文件: {f}")
    if not issues and not bad_dirs:
        print("  ✅ 抽查无异常")
print("\n体检完成（只读）")
