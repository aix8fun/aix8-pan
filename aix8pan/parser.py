"""文件名解析器（简化自 LitePan mediaorganize/rules 的核心思想）

从文件名/目录名中解析：
- 标题 / 年份
- 季集（S01E02 / 第X季第X集 / E02）
- 技术标签（分辨率/片源/编码/HDR/音频/全景声）
- TMDB ID（{tmdb-N} / {tmdbid-N}）

技术标签按 naming_spec.TECH_ORDER 归一为**规范顺序**「分辨率 片源 编码 HDR 音频 Atmos」，
空格分隔；v2.1 起技术段整体包方括号由模板提供（`[{tech}]`），tech 变量本身不带括号。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .naming_spec import TECH_ORDER, TECH_SEP

MEDIA_EXTS = {
    ".mkv", ".mp4", ".avi", ".wmv", ".mov", ".flv", ".ts", ".m2ts",
    ".iso", ".rmvb", ".rm", ".webm", ".mpg", ".mpeg", ".m4v", ".3gp",
}
COMPANION_SUFFIXES = (
    "-poster", "-fanart", "-clearlogo", "-clearart", "-thumb", "-banner",
    "-landscape", "-disc", "-backdrop", "-logo",
)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
# tMM / Kodi 标准：作品目录级图片用「无前缀固定名」，不带主文件名前缀
ARTWORK_STEMS = {
    "poster", "fanart", "backdrop", "logo", "clearlogo", "clearart",
    "banner", "thumb", "landscape", "disc", "keyart", "folder", "cover",
    "movie", "tvshow", "season",
}
COMPANION_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx"}

TMDB_ID_RE = re.compile(r"\{\s*tmdb(?:id)?-(\d+)\s*\}", re.IGNORECASE)
YEAR_RE = re.compile(r"(?:^|[\s._\(\[])(19\d{2}|20\d{2})(?=[\s._\)\]\-]|$)")
SEASON_EP_RE = re.compile(r"[Ss](\d{1,2})[\s._-]?[Ee](\d{1,3})")
SEASON_EP_CN_RE = re.compile(r"第\s*(\d{1,2})\s*季\s*第\s*(\d{1,3})\s*[集话話期]")
SEASON_ONLY_RE = re.compile(r"[Ss](\d{1,2})\s*[Ee]")
EP_ONLY_RE = re.compile(r"(?:^|[\s._\-\[])[Ee][Pp]?[\s._]?(\d{1,3})(?!\d)")

RELEASE_TAG_RE = re.compile(
    r"[\(\[].*?(4K|UHD|BluRay|Blu-ray|REMUX|WEB-?DL|WEBRip|HDTV|DVDRip|HDR10\+?|DoVi|DV\b|Dolby\s*Vision|SDR|HLG"
    r"|H\.?26[45]|x26[45]|AVC|HEVC|AV1|XviD"
    r"|DD[P]?\+?(?:\d\.\d)?|AC3|EAC3|TrueHD|DTS-?HD(?:[-\s]?(?:MA|HRA))?|DTS[-:]?X|DTS|Atmos|AAC|FLAC|MP3|Opus"
    r"|\d{3,4}p|10bit|8bit|HDR|杜比视界|全景声).*?[\)\]]"
)
SITE_PREFIX_RE = re.compile(r"^\[.*?\]\s*")

# 技术标签 token 识别（命名分组 = 规范段位）
# 交替顺序即「同位置优先级」：source 先于 hdr，保证 DVDRip 不会被当成 DV。
TECH_TOKEN_RE = re.compile(
    r"(?P<resolution>4320p|2160p|1080[pi]|720p|576p|480p|8K|4K|UHD|2K)\b"
    r"|(?P<source>Blu-?ray(?:\s*REMUX)?|BDMV|REMUX|WEB-?DL|WEBRip|HDTV|DVDRip|DVDScr|BDRip)\b"
    r"|(?P<codec>H\.?\s?264|H\.?\s?265|HEVC|x264|x265|AVC|AV1|XviD|MPEG-?2)\b"
    r"|(?P<hdr>HDR10\+|HDR10|HDR|DoVi|Dolby\s*Vision|杜比视界|DV|HLG|SDR)\b"
    r"|(?P<atmos>Atmos|杜比全景声|全景声)\b"
    r"|(?P<audio>DTS-?HD(?:[-\s]?(?:MA|HRA))?|DTS[-:]?X|DTS|TrueHD|E-?AC-?3|AC-?3"
    r"|DDP\+?(?:\s?\d\.\d)?|DD\+|DD|AAC(?:\s?\d\.\d)?|FLAC|LPCM|PCM|Opus|MP3)\b",
    re.IGNORECASE)

# 兼容旧接口（供标题切割 / 外部引用）
QUALITY_TOKEN_RE = TECH_TOKEN_RE
RESOLUTION_RE = re.compile(r"(4320p|2160p|1080[pi]|720p|4K|UHD|2K|8K)", re.IGNORECASE)

RES_NORM = {
    "4320P": "4320p", "8K": "4320p",
    "2160P": "2160p", "4K": "2160p", "UHD": "2160p",
    "1080P": "1080p", "1080I": "1080p", "2K": "1080p",
    "720P": "720p", "576P": "576p", "480P": "480p",
}
SOURCE_NORM = {
    "BLURAY": "BluRay", "BLU-RAY": "BluRay", "BLU RAY": "BluRay",
    "BLURAY REMUX": "BluRay REMUX", "BLU-RAY REMUX": "BluRay REMUX",
    "BDMV": "BDMV", "REMUX": "REMUX",
    "WEBDL": "WEB-DL", "WEB-DL": "WEB-DL", "WEBRIP": "WEBRip",
    "HDTV": "HDTV", "DVDRIP": "DVDRip", "DVDSCR": "DVDScr", "BDRIP": "BDRip",
}
CODEC_NORM = {
    "H264": "H.264", "H.264": "H.264", "H 264": "H.264", "X264": "H.264", "AVC": "H.264",
    "H265": "H.265", "H.265": "H.265", "H 265": "H.265", "X265": "H.265", "HEVC": "H.265",
    "AV1": "AV1", "XVID": "XviD", "MPEG2": "MPEG-2", "MPEG-2": "MPEG-2",
}
HDR_NORM = {
    "HDR10+": "HDR10+", "HDR10": "HDR10", "HDR": "HDR",
    "DOVI": "DV", "DV": "DV", "DOLBY VISION": "DV", "杜比视界": "DV",
    "HLG": "HLG", "SDR": "SDR",
}
AUDIO_NORM = {
    # 存量（tMM）实测写法为准：51 部 `DTSHD-MA`、32 部 `DTS-X`、4 部 `DTS`
    "DTS-HD MA": "DTSHD-MA", "DTSHD MA": "DTSHD-MA", "DTSHD-MA": "DTSHD-MA",
    "DTSHD-HRA": "DTSHD-HRA", "DTS-HD HRA": "DTSHD-HRA", "DTSHD HRA": "DTSHD-HRA",
    "DTS-HD": "DTSHD", "DTSHD": "DTSHD",
    "DTS-X": "DTS-X", "DTS X": "DTS-X", "DTSX": "DTS-X", "DTS:X": "DTS-X",
    "DTS": "DTS",
    "TRUEHD": "TrueHD", "EAC3": "EAC3", "E-AC3": "EAC3", "AC3": "AC3", "AC-3": "AC3",
    "DDP": "DDP", "DD+": "DDP", "DD": "DD",
    "AAC": "AAC", "FLAC": "FLAC", "LPCM": "LPCM", "PCM": "PCM",
    "OPUS": "Opus", "MP3": "MP3",
}
ATMOS_NORM = {"ATMOS": "Atmos", "全景声": "Atmos", "杜比全景声": "Atmos"}

_SLOT_NORM = {
    "resolution": RES_NORM, "source": SOURCE_NORM, "codec": CODEC_NORM,
    "hdr": HDR_NORM, "audio": AUDIO_NORM, "atmos": ATMOS_NORM,
}


@dataclass
class ParsedName:
    title: str = ""
    year: str = ""
    season: int | None = None
    episode: int | None = None
    tmdb_id: str = ""
    tech: str = ""            # 原样保留的技术标签串（tMM 风格，空格分隔）
    resolution: str = ""      # 归一化分辨率（2160p/1080p/720p），用于分类展示
    is_media: bool = False
    is_companion: bool = False
    is_artwork: bool = False   # 作品/季目录级图片（poster/fanart/logo…），跟随目录不改名
    ext: str = ""
    raw: str = ""


def find_tmdb_id(name: str) -> str:
    m = TMDB_ID_RE.search(name)
    return m.group(1) if m else ""


def _strip_site_prefix(name: str) -> str:
    return SITE_PREFIX_RE.sub("", name, count=1)


def _norm_slot(slot: str, raw: str) -> str:
    """把匹配到的原始 token 归一为规范写法。"""
    t = re.sub(r"\s+", " ", raw.strip())
    if not t:
        return ""
    table = _SLOT_NORM.get(slot) or {}
    if t in table:                       # 精确命中（含中文键）
        return table[t]
    up = t.upper()
    if up in table:
        return table[up]
    return t


def extract_tech_fields(name: str) -> dict:
    """提取技术段位 → {resolution/source/codec/hdr/audio/atmos: 规范值}。

    同段位「首次出现胜出」；段位内部不做跨段位重排（重排由 render_tech 负责）。
    """
    found: dict[str, str] = {}
    for m in TECH_TOKEN_RE.finditer(name):
        for slot in TECH_ORDER:
            v = m.group(slot) if slot in m.groupdict() else None
            if v and slot not in found:
                found[slot] = _norm_slot(slot, v)
                break
    return found


def render_tech(fields: dict) -> str:
    """按 TECH_ORDER 拼接技术标签：`2160p TrueHD Atmos`（空格分隔、无方括号）。"""
    return TECH_SEP.join(fields[s] for s in TECH_ORDER if fields.get(s))


def extract_tech(name: str) -> tuple[str, str]:
    """从名字中提取规范顺序技术标签串 + 归一化分辨率。"""
    fields = extract_tech_fields(name)
    return render_tech(fields), fields.get("resolution", "")


def parse_media_name(name: str, is_dir: bool = False) -> ParsedName:
    """解析文件/目录名。"""
    p = ParsedName(raw=name, is_media=False)
    stem = name
    if not is_dir:
        dot = name.rfind(".")
        if dot > 0:
            stem, p.ext = name[:dot], name[dot:].lower()
        p.is_media = p.ext in MEDIA_EXTS
        base = stem.lower()
        if p.ext in IMAGE_EXTS and (base in ARTWORK_STEMS or base.rstrip("0123456789") in ARTWORK_STEMS):
            # 无前缀的作品级图片：poster.jpg / fanart.jpg / logo.png / season01-poster.jpg
            p.is_companion = True
            p.is_artwork = True
        elif any(base.endswith(s) for s in COMPANION_SUFFIXES) and p.ext in COMPANION_EXTS:
            p.is_companion = True
            p.is_artwork = p.ext in IMAGE_EXTS
        if p.ext in (".nfo",) or p.is_companion:
            p.is_media = False

    work = _strip_site_prefix(stem)
    p.tmdb_id = find_tmdb_id(work)
    work = TMDB_ID_RE.sub("", work).strip()

    # 季集（记录位置用于标题截断，不从 work 中删除）
    se_m = SEASON_EP_RE.search(work)
    ep_m = None
    if se_m:
        p.season, p.episode = int(se_m.group(1)), int(se_m.group(2))
    else:
        se_m = SEASON_EP_CN_RE.search(work)
        if se_m:
            p.season, p.episode = int(se_m.group(1)), int(se_m.group(2))
        else:
            ep_m = EP_ONLY_RE.search(work)
            if ep_m:
                p.episode = int(ep_m.group(1))

    # 年份
    ym = YEAR_RE.search(work)
    if ym:
        p.year = ym.group(1)

    # 技术标签
    p.tech, p.resolution = extract_tech(work)

    # 标题 = 第一个「结构 token」（季集/集号/年份/技术标签）之前的文本
    cut = len(work)
    for m in (se_m, ep_m, ym, QUALITY_TOKEN_RE.search(work)):
        if m:
            cut = min(cut, m.start())
    title = _strip_site_prefix(work[:cut])
    title = RELEASE_TAG_RE.sub("", title)
    title = re.sub(r"[\[\]【】（）()]", " ", title)
    title = re.sub(r"[._]", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -_—·")
    p.title = title

    return p


# 规范**明确禁止**出现在文件名里的东西：
#   ① {tmdbid-N} / {tmdb-N} 标识 —— ID 只允许出现在作品目录名
#   ② 圆括号包裹的技术标签 —— v2.1 起规范为**方括号**（如 [2160p TrueHD Atmos]），
#      圆括号只用于年份；用 (2160p …) 属于旧工具产物
PAREN_TECH_RE = re.compile(
    r"\([^\]\)]*?(?:\d{3,4}p|\b4K\b|\bUHD\b|Blu-?ray|REMUX|WEB-?DL|HDR|H\.?26[45]|HEVC"
    r"|TrueHD|DTS|AAC|Atmos|FLAC|DDP|AC3)[^\]\)]*?\)",
    re.IGNORECASE)
# 兼容旧引用（语义已收窄为「圆括号技术标签」）
BRACKET_TECH_RE = PAREN_TECH_RE


def violates_filename_spec(name: str) -> bool:
    """文件名是否带有规范明确禁止的结构（ID 标识 / 圆括号技术标签）。

    用于「宽容判定」里识别**存量名本身就违规**的文件 —— 这类才允许改名，
    其它已就位的文件（英文原名、简化名）一律保留。
    v2.1：方括号技术标签是规范形态，不再视为违规。
    """
    return bool(TMDB_ID_RE.search(name)) or bool(PAREN_TECH_RE.search(name))


def looks_organized_folder(name: str, title: str, year: str) -> bool:
    """目录是否已是「标题 (年份)」形态（容忍可选的 {tmdbid-N} 尾巴）。

    宽进策略：目录名以「title (year)」开头，剩余部分为空或恰好是 ID 标识，
    即认为已整理——绝不因缺标识而误判未整理触发重命名。
    """
    if not title or not year:
        return False
    expect_prefix = f"{title} ({year})"
    if not name.startswith(expect_prefix):
        return False
    rest = name[len(expect_prefix):].strip()
    return rest == "" or bool(TMDB_ID_RE.fullmatch(rest))


def season_folder_name(season: int) -> str:
    return f"Season {season:02d}"
