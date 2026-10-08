"""解析器 / 命名引擎 / 命名规范 单元测试

样本全部取自用户 115 网盘 tMM 整理存量（真实字节核对过），目标形态为 v2.2 冻结规范：
  目录  大黄蜂 (2018) {tmdbid-424783}
  文件  大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso
  海报  大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos]-poster.jpg   ← 前缀式
  海报  大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos]-clearlogo.png
  nfo   大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].nfo          ← 与主文件同名
  剧集目录  三国演义 (1994) {tmdbid-72645}                        ← v2.2 起带 ID
  剧集文件  三国演义 - S01E01 - 桃园三结义 [2160p WEB-DL H265 AAC].mp4
  剧集  poster.jpg / fanart.jpg / season01-poster.jpg / tvshow.nfo（无前缀）
  容器  变形金刚（系列） / 漫威宇宙（主线）

存量旧形态（无方括号、`白夜追凶 - S01E01 - 第1集.mp4`）按「少改名」原则不追改，
解析器仍须正确识别（见 test_parse_tv_file 等）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aix8pan import naming_spec as spec
from aix8pan.parser import (
    extract_tech, extract_tech_fields, find_tmdb_id, looks_organized_folder,
    parse_media_name, render_tech, season_folder_name, violates_filename_spec,
)
from aix8pan.naming import NamingEngine, latin_title, sanitize

# 与 naming_spec v2.2 事实源一致的模板（不要写旧形态，否则测试会与冻结规范漂移）
NAMING_CFG = {
    "movie_folder_template": "{title} ({year}) {tmdbid_tag}",
    "tv_folder_template": "{title} ({year}) {tmdbid_tag}",
    "season_folder_template": "Season {season:02d}",
    "movie_file_template": "{title} {original} ({year}) [{tech}]",
    "tv_file_template": "{title} - {season_ep} - {episode_title} [{tech}]",
}


# ═══════════════ 解析 ═══════════════

def test_parse_movie_file():
    p = parse_media_name("大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos.iso")
    assert p.title == "大黄蜂 Bumblebee", p.title
    assert p.year == "2018"
    assert p.resolution == "2160p"
    assert p.tech == "2160p TrueHD Atmos", p.tech
    assert p.is_media


def test_parse_movie_file_cn_colon():
    """存量标题里的全角冒号必须原样保留。"""
    p = parse_media_name("变形金刚2：卷土重来 Transformers - Revenge of the Fallen (2009) 2160p TrueHD Atmos.iso")
    assert p.title == "变形金刚2：卷土重来 Transformers - Revenge of the Fallen", p.title
    assert p.year == "2009"
    assert p.tech == "2160p TrueHD Atmos"


def test_parse_tv_file():
    p = parse_media_name("白夜追凶 - S01E01 - 第1集.mp4")
    assert p.season == 1 and p.episode == 1
    assert p.title == "白夜追凶", p.title


def test_parse_tv_raw_release():
    """存量剧集原始发布名（点分隔、带片源/编码）也要能解析。"""
    p = parse_media_name("漫长的季节.The.Long.Season.S01E01.2023.2160p.NF.WEB-DL.H265.DDP2.0-LelveTV.mkv")
    assert p.season == 1 and p.episode == 1
    assert p.year == "2023"
    assert p.resolution == "2160p"
    assert p.tech == "2160p WEB-DL H.265 DDP2.0", p.tech


def test_parse_dirty_name():
    p = parse_media_name("[企业网盘xxx]蜘蛛侠.纵横宇宙.2024.1080p.WEB-DL.H265.mkv")
    assert p.year == "2024"
    assert p.resolution == "1080p"
    assert "蜘蛛侠" in p.title
    assert p.tech == "1080p WEB-DL H.265", p.tech


def test_parse_tmdb_id():
    assert find_tmdb_id("沙丘2 (2024) {tmdbid-693}") == "693"
    assert find_tmdb_id("蝙蝠侠：黑暗骑士 (2008) {tmdb-155}") == "155"
    p = parse_media_name("沙丘2 (2024) {tmdbid-693}")
    assert p.tmdb_id == "693"


def test_parse_companion():
    p = parse_media_name("大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos-poster.jpg")
    assert p.is_companion and not p.is_media


def test_parse_cn_season():
    p = parse_media_name("三国演义 第1季第3集.mp4")
    assert p.season == 1 and p.episode == 3


def test_organized_folder():
    assert looks_organized_folder("沙丘2 (2024) {tmdbid-693}", "沙丘2", "2024")
    assert looks_organized_folder("沙丘2 (2024)", "沙丘2", "2024")
    assert looks_organized_folder("白夜追凶 (2017)", "白夜追凶", "2017")
    assert not looks_organized_folder("白夜追凶 (2017) 1080p", "白夜追凶", "2017")
    assert not looks_organized_folder("沙丘2 (2024)", "沙丘3", "2024")


# ═══════════════ 技术标签（规范顺序）═══════════════

def test_tech_order_canonical():
    """技术标签必须按 分辨率 → 片源 → 编码 → HDR → 音频 → Atmos 重排。"""
    fields = extract_tech_fields("TrueHD Atmos 2160p H.265 BluRay DV")
    assert render_tech(fields) == "2160p BluRay H.265 DV TrueHD Atmos", render_tech(fields)


def test_tech_order_from_raw_release():
    """存量原始名 `2160p.DV.H.265.DDP 2.0` → 规范序重排为 `2160p H.265 DV DDP 2.0`。"""
    tech, res = extract_tech("Swords Into Plowshares.S01E01.2160p.DV.H.265.DDP 2.0")
    assert tech == "2160p H.265 DV DDP 2.0", tech
    assert res == "2160p"


def test_tech_extract_ignores_brackets():
    """tech 变量本身不含方括号（方括号由模板提供）；段内空格分隔。"""
    tech, _ = extract_tech("沙丘2 (2024) [2160p] [TrueHD] [Atmos]")
    assert tech == "2160p TrueHD Atmos", tech
    assert "[" not in tech and "]" not in tech


def test_tech_dvdrip_not_misread_as_dv():
    """DVDRip 不能被解析成 DV(HDR) + Rip。"""
    fields = extract_tech_fields("Movie (2020) 1080p DVDRip XviD AC3")
    assert fields.get("hdr", "") == "", fields
    assert fields.get("source") == "DVDRip", fields


def test_tech_audio_matches_legacy_tmm_forms():
    """音频规范 = 存量实测写法（tMM）：DTSHD-MA / DTS-X，不能写成 DTS-HD MA / DTS:X。

    依据：全库实测 51 部 `DTSHD-MA`、32 部 `DTS-X`、4 部 `DTS`。
    若归一到别的写法会引发 80+ 文件的全库重命名。
    """
    for raw, want in [
        ("1080p DTSHD-MA", "1080p DTSHD-MA"),      # 存量原样
        ("1080p DTS-HD MA", "1080p DTSHD-MA"),     # 别名归一
        ("2160p DTS-X", "2160p DTS-X"),            # 存量原样
        ("2160p DTS:X", "2160p DTS-X"),            # 别名归一
        ("1080p DTS", "1080p DTS"),
        ("2160p TrueHD Atmos", "2160p TrueHD Atmos"),
    ]:
        got, _ = extract_tech(f"某片 (2020) {raw}.iso")
        assert got == want, f"{raw} → {got}（应为 {want}）"


def test_tech_dtshd_ma_not_truncated():
    """回归：`DTSHD-MA` 曾被正则截断成 `DTSHD`（丢掉 -MA）。"""
    fields = extract_tech_fields("007之太空城 Moonraker (1979) 1080p DTSHD-MA.iso")
    assert fields.get("audio") == "DTSHD-MA", fields


# ═══════════════ 命名引擎 ═══════════════

def test_naming_movie():
    eng = NamingEngine(NAMING_CFG)
    v = eng.build_vars(title="沙丘2", original="Dune - Part Two", year="2024",
                       tech="2160p TrueHD Atmos", tmdb_id="693134")
    assert eng.folder_name(v, "movie") == "沙丘2 (2024) {tmdbid-693134}", eng.folder_name(v, "movie")
    name = eng.movie_file_name(v, ".mkv")
    assert name == "沙丘2 Dune - Part Two (2024) [2160p TrueHD Atmos].mkv", name


def test_naming_movie_matches_existing_library():
    """命名引擎输出必须与存量逐字一致 —— 这是「零重命名」的前提（v2.2 方括号形态）。"""
    eng = NamingEngine(NAMING_CFG)
    v = eng.build_vars(title="大黄蜂", original="Bumblebee", year="2018",
                       tech="2160p TrueHD Atmos", tmdb_id="424783")
    stem = "大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos]"
    assert eng.folder_name(v, "movie") == "大黄蜂 (2018) {tmdbid-424783}"
    assert eng.movie_file_name(v, ".iso") == stem + ".iso"
    assert eng.artwork_name("poster", stem) == stem + "-poster.jpg"
    assert eng.artwork_name("clearlogo", stem) == stem + "-clearlogo.png"
    assert eng.nfo_name("movie", stem) == stem + ".nfo"


def test_naming_tv():
    eng = NamingEngine(NAMING_CFG)
    v = eng.build_vars(title="白夜追凶", year="2017", season=1, episode=1,
                       episode_title="第1集")
    assert eng.tv_file_name(v, ".mp4") == "白夜追凶 - S01E01 - 第1集.mp4", eng.tv_file_name(v, ".mp4")
    assert eng.season_folder_name(1) == "Season 01"
    assert eng.folder_name(v, "tv") == "白夜追凶 (2017)"


def test_naming_tv_id_in_folder():
    """剧集目录 v2.2 起带 {tmdbid-N}（与电影库统一）；无 ID 时不留空括号。"""
    eng = NamingEngine(NAMING_CFG)
    v = eng.build_vars(title="白夜追凶", year="2017", tmdb_id="12345")
    assert eng.folder_name(v, "tv") == "白夜追凶 (2017) {tmdbid-12345}"
    assert eng.folder_name(v, "movie") == "白夜追凶 (2017) {tmdbid-12345}"
    v2 = eng.build_vars(title="白夜追凶", year="2017")
    assert eng.folder_name(v2, "tv") == "白夜追凶 (2017)"


def test_naming_empty_tech():
    eng = NamingEngine(NAMING_CFG)
    v = eng.build_vars(title="aa", year="", tech="", tmdb_id="")
    assert eng.movie_file_name(v, ".mkv") == "aa.mkv", eng.movie_file_name(v, ".mkv")


def test_naming_tv_no_episode_title():
    eng = NamingEngine(NAMING_CFG)
    v = eng.build_vars(title="太平年", year="2026", season=1, episode=13)
    assert eng.tv_file_name(v, ".mp4") == "太平年 - S01E13.mp4", eng.tv_file_name(v, ".mp4")


# ═══════════════ sanitize ═══════════════

def test_sanitize_colon_rules():
    """半角冒号 → ' - '（存量 Dune - Part Two）；全角冒号保留（存量 变形金刚2：卷土重来）。"""
    assert sanitize("Dune: Part Two") == "Dune - Part Two"
    assert sanitize("变形金刚2：卷土重来") == "变形金刚2：卷土重来"
    assert sanitize("砂之女：.奇怪的") == "砂之女：.奇怪的"


def test_sanitize_illegal_and_trim():
    assert sanitize("a/b\\c*d?e") == "a-b-c-d-e"
    assert sanitize("trailing... ") == "trailing"
    assert len(sanitize("长" * 300).encode("utf-8")) <= 235


def test_latin_title():
    assert latin_title("Dune - Part Two") == "Dune - Part Two"
    assert latin_title("沙丘2") == ""
    assert latin_title("少年的你") == ""


# ═══════════════ artwork 识别与归一 ═══════════════

def test_artwork_recognition():
    for n in ["poster.jpg", "fanart.jpg", "logo.png", "backdrop.jpg",
              "banner.jpg", "thumb.jpg", "clearlogo.png", "season01-poster.jpg"]:
        p = parse_media_name(n)
        assert p.is_companion, f"{n} 应为伴随文件"
        assert p.is_artwork, f"{n} 应为作品级图片"
        assert not p.is_media, f"{n} 不应是媒体文件"
    p = parse_media_name("大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos-poster.jpg")
    assert p.is_companion and p.is_artwork
    assert parse_media_name("大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos.iso").is_media
    assert not parse_media_name("movie.nfo").is_media


def test_artwork_kind_parse():
    assert spec.parse_artwork("poster.jpg") == "poster"
    assert spec.parse_artwork("logo.png") == "clearlogo"
    assert spec.parse_artwork("backdrop.jpg") == "fanart"
    assert spec.parse_artwork("season01-poster.jpg") == "season-poster"
    assert spec.parse_artwork("大黄蜂 Bumblebee (2018)-poster.jpg") == "poster"
    # thumb/banner 等 Kodi 既有后缀不属规范管理范围 → 不识别、不归一
    assert spec.parse_artwork("藏海花 - S01E01 - 某集-thumb.jpg") == ""
    assert spec.parse_artwork("random.jpg") == ""


def test_artwork_alias_scope():
    """只有 logo→clearlogo、backdrop→fanart 两条归一；thumb/banner 等不动。"""
    assert spec.canonical_artwork("thumb") == "thumb"
    assert spec.canonical_artwork("banner") == "banner"
    assert spec.canonical_artwork("clearart") == "clearart"
    stem = "藏海花 - S01E01 - 某集"
    assert spec.normalize_artwork_name(f"{stem}-thumb.jpg", "") == f"{stem}-thumb.jpg"


def test_common_stem_multidisc():
    """多碟作品的 artwork 前缀必须去掉碟号（存量指环王实例）。"""
    a = "指环王1：护戒使者 The Lord of the Rings - The Fellowship of the Ring (2001) 2160p TrueHD Atmos"
    assert spec.common_stem([a + " DISC1", a + " DISC2"]) == a
    assert spec.common_stem([a + ".CD1", a + ".CD2"]) == a
    assert spec.common_stem([a]) == a
    assert spec.common_stem([]) == ""
    # 单文件场景不受影响
    assert spec.common_stem(["大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos.iso".rsplit(".", 1)[0]]) == \
        "大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos"


def test_artwork_name_normalize():
    stem = "大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos"
    # 电影：前缀式
    assert spec.normalize_artwork_name("poster.jpg", stem) == f"{stem}-poster.jpg"
    assert spec.normalize_artwork_name("logo.png", stem) == f"{stem}-clearlogo.png"
    assert spec.normalize_artwork_name("backdrop.jpg", stem) == f"{stem}-fanart.jpg"
    # 剧集：无前缀
    assert spec.normalize_artwork_name("poster.jpg", "") == "poster.jpg"
    assert spec.normalize_artwork_name("logo.png", "") == "clearlogo.png"
    # 已规范 → 幂等
    assert spec.normalize_artwork_name(f"{stem}-poster.jpg", stem) == f"{stem}-poster.jpg"
    # 非 artwork 不动
    assert spec.normalize_artwork_name("movie.mkv", stem) == "movie.mkv"


def test_nfo_name():
    assert spec.nfo_name("tv") == "tvshow.nfo"
    assert spec.nfo_name("movie") == "movie.nfo"
    assert spec.nfo_name("movie", "aa (2020) 1080p") == "aa (2020) 1080p.nfo"
    assert spec.normalize_nfo_name("movie.nfo", "movie", "aa (2020) 1080p") == "aa (2020) 1080p.nfo"


# ═══════════════ 容器目录 ═══════════════

def test_container_detection():
    for n in ["合集", "专辑", "0-待整理", "变形金刚（系列）", "漫威宇宙（主线）"]:
        assert spec.is_container_dir(n), n
    assert spec.container_kind("变形金刚（系列）") == "series"
    assert spec.container_kind("漫威宇宙（主线）") == "mainline"
    assert spec.container_kind("专辑") == "album"
    assert spec.container_kind("0-待整理") == "inbox"
    # 作品目录不是容器
    for n in ["大黄蜂 (2018) {tmdbid-424783}", "白夜追凶 (2017)", "小猪佩奇(2004)",
              "如果国宝会说话", "红海行动（系列）2"]:
        assert not spec.is_container_dir(n), n


def test_series_dir_name():
    assert spec.series_dir_name("变形金刚") == "变形金刚（系列）"
    assert spec.series_dir_name("变形金刚（系列）") == "变形金刚（系列）"
    assert spec.series_dir_name("漫威宇宙（主线）") == "漫威宇宙（主线）"


def test_season_folder_name_helper():
    assert season_folder_name(1) == "Season 01"
    assert spec.season_poster_name(3) == "season03-poster.jpg"


def test_violates_filename_spec():
    """文件名里的 ID 标识 / 圆括号技术标签 —— 规范明确禁止（v2.1 起方括号是规范形态）。"""
    assert violates_filename_spec("八仙！ (2026) {tmdb-1633056} [1080p].mkv")
    assert violates_filename_spec("年会不能停！ (2023) {tmdbid-1173076} [2160p H.265].mp4")
    assert violates_filename_spec("某电影 (2020) (BluRay).mkv")
    # 合规名不得被误判：方括号技术段（v2.1 规范形态）
    assert not violates_filename_spec("大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso")
    assert not violates_filename_spec("指环王1：护戒使者 The Lord of the Rings - The Fellowship of the Ring (2001) [2160p TrueHD Atmos] DISC1.iso")
    assert not violates_filename_spec("白夜追凶 - S01E01 - 第1集.mp4")
    assert not violates_filename_spec("漫长的季节.The.Long.Season.S01E01.2023.2160p.NF.WEB-DL.H265.DDP2.0-LelveTV.mkv")
    # 普通括号年份不算
    assert not violates_filename_spec("沙丘2 (2024) [2160p TrueHD Atmos].mkv")


def test_spec_dict_complete():
    d = spec.spec_dict()
    for k in ("movie_folder_template", "tv_folder_template", "movie_file_template",
              "tech_order", "artwork_exts", "artwork_rule"):
        assert k in d, k
    assert d["tech_order"] == ["resolution", "source", "codec", "hdr", "audio", "atmos"]


# ── 多版本（1080p + 2160p）与多碟（DISC1/DISC2）────────────────

_STEM_1080 = "007：大战皇家赌场 Casino Royale (2006) 1080p AC3"
_STEM_2160 = "007：大战皇家赌场 Casino Royale (2006) 2160p DTSHD-MA"


def test_same_version_multidisc():
    """多碟属同一版本 → 用公共前缀（去掉碟号）。"""
    d1 = "指环王1：护戒使者 The Lord of the Rings (2001) 2160p TrueHD Atmos DISC1"
    d2 = "指环王1：护戒使者 The Lord of the Rings (2001) 2160p TrueHD Atmos DISC2"
    assert spec.is_same_version([d1, d2])
    assert spec.common_stem([d1, d2]) == \
        "指环王1：护戒使者 The Lord of the Rings (2001) 2160p TrueHD Atmos"
    # CD1/CD2、Part1/Part2、点号分卷写法
    assert spec.is_same_version(["电影 (2020) 1080p BluRay CD1", "电影 (2020) 1080p BluRay CD2"])
    assert spec.is_same_version(["Movie.2020.1080p.BluRay.Part1", "Movie.2020.1080p.BluRay.Part2"])
    assert spec.common_stem(["电影 (2020) 1080p BluRay CD1",
                             "电影 (2020) 1080p BluRay CD2"]) == "电影 (2020) 1080p BluRay"


def test_multi_version_detected():
    """不同分辨率/音频 = 多版本共存，不得并成一个前缀。"""
    assert not spec.is_same_version([_STEM_1080, _STEM_2160])
    assert spec.common_stem([_STEM_1080, _STEM_2160]) == \
        "007：大战皇家赌场 Casino Royale (2006)"      # 公共前缀（不可用作 artwork 前缀）
    assert spec.is_same_version([_STEM_1080])          # 单版本恒 True


def test_artwork_owner_longest_match():
    stems = [_STEM_1080, _STEM_2160]
    assert spec.artwork_owner(f"{_STEM_1080}-poster.jpg", stems) == _STEM_1080
    assert spec.artwork_owner(f"{_STEM_2160}-clearlogo.png", stems) == _STEM_2160
    assert spec.artwork_owner(f"{_STEM_2160}-fanart.jpg", stems) == _STEM_2160
    # 无前缀式 / 无关图片
    assert spec.artwork_owner("poster.jpg", stems) == ""
    assert spec.artwork_owner("随机图.jpg", stems) == ""
    # 前缀包含关系：长 stem 优先
    assert spec.artwork_owner("电影 (2020) 1080p-poster.jpg",
                              ["电影 (2020)", "电影 (2020) 1080p"]) == "电影 (2020) 1080p"


def test_unprefixed_artwork_and_nfo_owner():
    assert spec.is_unprefixed_artwork("poster.jpg")
    assert spec.is_unprefixed_artwork("backdrop.jpg")
    assert not spec.is_unprefixed_artwork(f"{_STEM_1080}-poster.jpg")
    assert not spec.is_unprefixed_artwork("season01-poster.jpg")
    assert spec.nfo_owner(f"{_STEM_2160}.nfo", [_STEM_1080, _STEM_2160]) == _STEM_2160
    assert spec.nfo_owner("movie.nfo", [_STEM_1080]) == ""
    assert spec.nfo_owner(f"{_STEM_1080}.srt", [_STEM_1080]) == ""


def test_multi_version_artwork_roundtrip():
    """多版本目录重命名时，每个版本的 artwork 各自跟随，不得并成一个前缀。"""
    eng = NamingEngine({"movie_folder_template": "{title} ({year}) {tmdbid_tag}",
                        "movie_file_template": "{title} {original} ({year}) [{tech}]"})
    stems = [_STEM_1080, _STEM_2160]
    for st in stems:
        owner = spec.artwork_owner(f"{st}-poster.jpg", stems)
        assert owner == st
        assert spec.normalize_artwork_name(f"{st}-poster.jpg", owner) == f"{st}-poster.jpg"


def test_multidisc_artwork_follows_common_prefix():
    """多碟作品：artwork/nfo 用**公共前缀**（不带碟号）——存量指环王形态。"""
    base = "指环王1：护戒使者 The Lord of the Rings (2001) 2160p TrueHD Atmos"
    d1, d2 = f"{base} DISC1", f"{base} DISC2"
    stems = [d1, d2]
    assert spec.artwork_owner(f"{base}-poster.jpg", stems) == base
    assert spec.artwork_owner(f"{base}-fanart.jpg", stems) == base
    assert spec.nfo_owner(f"{base}.nfo", stems) == base
    # 若某碟自带 artwork，则优先归属该碟（最长匹配），不误并到公共前缀
    assert spec.artwork_owner(f"{d1}-poster.jpg", stems) == d1
    assert spec.nfo_owner(f"{d2}.nfo", stems) == d2
    # 无前缀式仍不归属任何前缀
    assert spec.artwork_owner("poster.jpg", stems) == ""


# ═══════════════ 规划器动作展开 ═══════════════

def test_finalize_whole_dir_move_with_rename():
    """目录改名 + 文件改名：只发 1 个 move_dir + N 个 rename，**绝不预建目标目录**。

    回归 bug：旧实现先 mkdir(目标同名目录) 再 move_dir + rename → 两者撞名。
    """
    from aix8pan.planner import Planner
    plan = {
        "source": "/lib/inbox",
        "groups": [{
            "source_dir": "/lib/old", "target_path": "/lib/new",
            "files": [
                {"name": "a.iso", "new_name": "b.iso", "cur_dir": "/lib/old",
                 "dst_dir": "/lib/new", "kind": "media"},
                {"name": "a.nfo", "new_name": "b.nfo", "cur_dir": "/lib/old",
                 "dst_dir": "/lib/new", "kind": "companion"},
            ],
        }],
        "actions": [], "summary": {}, "skips": [], "unmatched": [],
    }
    p = Planner.__new__(Planner)          # _finalize 不需要 client/tmdb
    p._finalize(plan)
    kinds = [a["action"] for a in plan["actions"]]
    assert kinds == ["move_dir", "rename", "rename"], kinds
    assert plan["groups"][0]["_whole_dir_move"] is True
    mv = plan["actions"][0]
    assert (mv["name"], mv["dst_name"]) == ("old", "new")
    assert "mkdir" not in kinds, "整目录搬移不应预建目标目录"


def test_finalize_keeps_mkdir_for_non_relocatable():
    """文件要被搬进**新建的子目录**（如剧集 Season 01）时，必须 mkdir + 逐文件移动。"""
    from aix8pan.planner import Planner
    plan = {
        "source": "/lib/inbox",
        "groups": [{
            "source_dir": "/lib/src", "target_path": "/lib/lib/new",
            "files": [
                {"name": "a.s01e01.mkv", "new_name": "剧 - S01E01.mkv",
                 "cur_dir": "/lib/src", "dst_dir": "/lib/lib/new/Season 01",
                 "kind": "media"},
            ],
        }],
        "actions": [], "summary": {}, "skips": [], "unmatched": [],
    }
    p = Planner.__new__(Planner)
    p._finalize(plan)
    kinds = [a["action"] for a in plan["actions"]]
    assert kinds == ["mkdir", "move", "rename"], kinds
    assert plan["groups"][0]["_whole_dir_move"] is False


def test_finalize_others_block_whole_dir_move():
    """组内有未归类文件（readme/压缩包）时不得整目录搬移 —— 否则会把它们一起带走。"""
    from aix8pan.planner import Planner
    plan = {
        "source": "/lib/inbox",
        "groups": [{
            "source_dir": "/lib/src", "target_path": "/lib/lib/new",
            "others": ["readme.txt"],
            "files": [
                {"name": "a.mkv", "new_name": "a.mkv", "cur_dir": "/lib/src",
                 "dst_dir": "/lib/lib/new", "kind": "media"},
            ],
        }],
        "actions": [], "summary": {}, "skips": [], "unmatched": [],
    }
    p = Planner.__new__(Planner)
    p._finalize(plan)
    kinds = [a["action"] for a in plan["actions"]]
    assert plan["groups"][0]["_whole_dir_move"] is False
    assert "move_dir" not in kinds, kinds
    assert kinds == ["mkdir", "move"], kinds


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
