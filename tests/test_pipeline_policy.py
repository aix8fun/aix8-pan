"""管线策略单元测试：剧集形态统一规则（2026-10-09 用户拍板）

规则：季目录只留视频（+字幕）；剧根只留标准 5 件套。
- 季目录内：一切非视频、非字幕文件 → 删（集级 nfo / -thumb.jpg / season.nfo…）
- 剧根：banner / thumb / background / backdrop / seasonNN-banner /
  seasonNN-thumb / theme.mp3 → 删
- 字幕永远保留；poster/fanart/clearlogo/seasonNN-poster/tvshow.nfo 不属于 purge
（归一分支负责）；电影不受影响。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan.pipeline.planner import is_tv_purge_file
from aix8pan.pipeline.scraper import _nfo_outdated


# ═══════════════ 季目录规则 ═══════════════

def test_season_ep_nfo_purged():
    assert is_tv_purge_file("伪装者 - S01E01 - 集名.nfo", True)
    assert is_tv_purge_file("Empresses.in.the.Palace.S01E29.2011.nfo", True)


def test_season_thumb_purged():
    assert is_tv_purge_file("庆余年 - S01E01 - 范闲脱胎换骨-thumb.jpg", True)


def test_season_nfo_purged():
    assert is_tv_purge_file("season.nfo", True)


def test_season_video_kept():
    assert not is_tv_purge_file("伪装者 - S01E01 - 集名 [2160p WEB-DL H.265 AAC].mp4", True)
    assert not is_tv_purge_file("权力的游戏 - S01E01 - 凛冬将至.mkv", True)


def test_season_subtitle_kept():
    assert not is_tv_purge_file("伪装者 - S01E01 - 集名.chs.srt", True)
    assert not is_tv_purge_file("庆余年 - S01E01.ass", True)


# ═══════════════ 剧根规则 ═══════════════

def test_root_legacy_art_purged():
    for n in ("banner.jpg", "thumb.jpg", "background.jpg", "backdrop.jpg",
              "theme.mp3", "season01-banner.jpg", "season08-thumb.jpg"):
        assert is_tv_purge_file(n, False), n


def test_root_standard_set_kept():
    for n in ("poster.jpg", "fanart.jpg", "clearlogo.png", "tvshow.nfo",
              "season01-poster.jpg", "season12-poster.jpg"):
        assert not is_tv_purge_file(n, False), n


def test_root_subtitle_kept():
    assert not is_tv_purge_file("台词.srt", False)


# ═══════════════ tvshow.nfo 新旧判定 ═══════════════

_PROJECT_NFO = """<?xml version="1.0"?>
<tvshow><title>伪装者</title><seasoncount>1</seasoncount></tvshow>"""

_TMM_NFO = """<?xml version="1.0"?>
<tvshow><title>伪装者</title><actor><name>胡歌</name></actor></tvshow>"""

_OLD_NFO = """<?xml version="1.0"?>
<tvshow><title>伪装者</title><season>-1</season><episode>-1</episode>
<uniqueid type="imdb" default="true">tt5154296</uniqueid></tvshow>"""


def test_nfo_project_template_kept():
    assert not _nfo_outdated(_PROJECT_NFO)


def test_nfo_tmm_rich_kept():
    assert not _nfo_outdated(_TMM_NFO)
    assert not _nfo_outdated("<tvshow><credits>x</credits></tvshow>")


def test_nfo_old_broken_rewritten():
    assert _nfo_outdated(_OLD_NFO)
    assert _nfo_outdated("<tvshow><title>x</title></tvshow>")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} 项全部通过")
