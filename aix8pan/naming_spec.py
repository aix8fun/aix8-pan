"""命名规范单一事实源（AIX8-Pan Naming Spec v2）

本模块是**唯一**的命名规则来源：模板、artwork 文件名、技术标签顺序、
容器目录判定全部从这里取。其它模块不得再硬编码命名形态。

**当前状态：v2.2，2026-10-08「剧集」规则冻结**（`SCOPE_STATUS["movie"]/["tv"] == "frozen"`）。
冻结 = 用户已确认满意，规则不再随讨论漂移；改规则必须走 SPEC.md §0 的变更流程，
并用 `tests/check_spec.py` 守门。动画/纪录片等仍为草案，待逐条确认后冻结。

v2.0 → v2.1（2026-10-07，用户拍板方案 B1）：
  电影文件名的技术段整体加方括号，分辨率随技术段一并进括号：
    `黑寡妇 Black Widow (2021) 2160p TrueHD Atmos.iso`
    → `黑寡妇 Black Widow (2021) [2160p TrueHD Atmos].iso`
  依据：Plex 官方（方括号内文本被忽略）、Radarr/TRaSH、tMM 社区模板均如此；
  目录名不变（不含技术段）；伴随文件（nfo/poster/fanart/clearlogo/字幕）随主文件主干同步。

v2.1 → v2.2（2026-10-08，用户拍板）：
  剧集规则冻结，两处与旧草案不同：
  ① 剧集作品目录**带 {tmdbid-N}**（与电影库统一；Plex/Jellyfin/Emby/Sonarr 业界均推荐
     目录名带 ID 以保证精确匹配、防同名剧歧义）；
  ② 剧集单集文件名用**真实集名 + 方括号技术标签**：
     `三国演义 - S01E01 - 桃园三结义 [2160p WEB-DL H265 AAC].mp4`
     （真实集名来自 TMDB season 接口；技术标签风格与电影 B1 一致）。

规范来源：从用户 115 网盘 tMM 整理存量反向提炼（见 SPEC.md）。

────────────────────────────────────────────────────────────
存量实测样本（v2.1 目标形态）
────────────────────────────────────────────────────────────
电影作品目录 : 大黄蜂 (2018) {tmdbid-424783}
电影主文件   : 大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso
电影海报     : 大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos]-poster.jpg   ← 前缀式
电影 logo    : 大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos]-clearlogo.png
电影 nfo     : 大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].nfo          ← 与主文件同名
电影字幕     : 大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].zh-CN.srt    ← 语言码点号分隔
             : 大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].en.srt
剧集作品目录 : 三国演义 (1994) {tmdbid-72645}                        ← v2.2 起带 ID
剧集季目录   : Season 01
剧集文件     : 三国演义 - S01E01 - 桃园三结义 [2160p WEB-DL H265 AAC].mp4
剧集海报     : poster.jpg / fanart.jpg / clearlogo.png                ← 无前缀
剧集季海报   : season01-poster.jpg
剧集 nfo     : tvshow.nfo
系列容器     : 变形金刚（系列） / 漫威宇宙（主线）                       ← 全角括号
"""
from __future__ import annotations

import re

# ═════════════════════════════════════════════════════════════
# 规范版本与冻结状态
# ═════════════════════════════════════════════════════════════
# 冻结含义：该分类的规则已由用户确认「满意」，**不再随讨论漂移**。
# 任何改动都必须走 SPEC.md §0 的「变更流程」（改本文件 → 同步文档 →
# 跑 tests/check_spec.py → 跑库审计确认存量仍全合规）。
SPEC_VERSION = "2.2"
SPEC_FROZEN_AT = "2026-10-07"
TV_FROZEN_AT = "2026-10-08"

# 各分类的规则状态：frozen = 已冻结；draft = 草案（尚未逐条确认）
SCOPE_STATUS: dict[str, str] = {
    "movie": "frozen",
    "tv": "frozen",
    "anime": "draft",
    "doc": "draft",
    "music": "draft",
    "book": "draft",
}

# ── 分类根目录（固定形态 {NN}-{中文名}）────────────────────────
CATEGORY_ROOTS = {
    "movie": "01-电影",
    "tv": "02-剧集",
    "anime": "03-动画",
    "doc": "04-纪录片",
    "music": "00-音乐",
    "book": "11-电子书",
}

# ── 容器目录：只装「作品目录」，自身不装媒体 ──────────────────
# 固定名容器
FIXED_CONTAINERS = {"0-待整理", "合集", "专辑", "待整理"}
# 后缀式容器（全角括号是规范形态）
SERIES_SUFFIX = "（系列）"
MAINLINE_SUFFIX = "（主线）"
CONTAINER_INBOX = "0-待整理"          # 「待整理」收件箱
INBOX_ALIASES = {"0-待整理", "待整理", "AA-TODO"}

# ── 作品目录模板 ─────────────────────────────────────────────
# 电影：必带 tmdbid 标识（存量 100% 带）
# 剧集：v2.2 起同样必带 {tmdbid-N}（业界 Plex/Jellyfin/Emby/Sonarr 均推荐；
#       与电影库统一标识写法）
MOVIE_FOLDER_TEMPLATE = "{title} ({year}) {tmdbid_tag}"
TV_FOLDER_TEMPLATE = "{title} ({year}) {tmdbid_tag}"
# 季目录：两位补零
SEASON_FOLDER_TEMPLATE = "Season {season:02d}"

# ── 作品文件模板 ─────────────────────────────────────────────
# 电影：中文标题 空格 英文原名 (年份) [技术标签]   ← v2.1：技术段整体包方括号
#       （tech 为空时方括号整段消失，见 naming.NamingEngine._strip_empty）
MOVIE_FILE_TEMPLATE = "{title} {original} ({year}) [{tech}]"
# 剧集：标题 - SxxExx - 真实单集标题 [技术标签]   ← v2.2：真实集名（TMDB season 接口）
#       技术段整体包方括号，风格与电影 B1 一致；tech 为空时方括号整段消失
TV_FILE_TEMPLATE = "{title} - {season_ep} - {episode_title} [{tech}]"

# ── 技术标签 ─────────────────────────────────────────────────
# 段序固定；空段整段消失（不留双空格）
TECH_ORDER = ("resolution", "source", "codec", "hdr", "audio", "atmos")
TECH_LABELS = {
    "resolution": "分辨率",
    "source": "片源",
    "codec": "视频编码",
    "hdr": "HDR",
    "audio": "音频编码",
    "atmos": "全景声",
}
# 技术标签分隔符：**空格**（段内空格分隔；v2.1 起技术段整体包方括号，方括号由
# MOVIE_FILE_TEMPLATE 提供，不属于 tech 变量本身）
TECH_SEP = " "

# ── 字幕（v2.1 新增，业界 Emby/Kodi 约定）────────────────────
# 命名：{主文件主体}.{语言码}.srt —— 语言码用**点号**分隔（不是 artwork 的连字符）
SUBTITLE_EXTS = (".srt", ".ass", ".ssa")
SUBTITLE_LANGS = {"zh-CN": "简体中文", "zh-TW": "繁体中文", "en": "英文"}

# ── artwork（海报等伴随文件）──────────────────────────────────
# 规范关键字顺序与扩展名
ARTWORK_EXTS = {
    "poster": ".jpg",
    "fanart": ".jpg",
    "clearlogo": ".png",
}
# 存量等价别名 → 规范关键字
# 只做两条真正的归一：logo.png → clearlogo.png ; backdrop.jpg → fanart.jpg
# （thumb / banner / clearart / landscape 等是 Kodi 既有语义，**不要**改）
ARTWORK_ALIASES = {
    "logo": "clearlogo",
    "backdrop": "fanart",
}
# 季海报文件名
SEASON_POSTER_FMT = "season{s:02d}-poster.jpg"

# ── NFO ─────────────────────────────────────────────────────
TV_NFO = "tvshow.nfo"
MOVIE_NFO = "movie.nfo"          # 电影无主文件可继承前缀时的兜底

# ── 收件箱默认落点 ───────────────────────────────────────────
DEFAULT_INBOX = "AA-TODO"


# ═════════════════════════════════════════════════════════════
# 判定 / 生成 辅助
# ═════════════════════════════════════════════════════════════

def is_container_dir(name: str) -> bool:
    """是否为「组织容器」目录（合集/专辑/（系列）/（主线）/待整理）。

    容器目录只作命名空间，不参与整理，也不应被当成作品组解析。
    """
    n = (name or "").strip()
    if not n:
        return False
    if n in FIXED_CONTAINERS:
        return True
    return n.endswith(SERIES_SUFFIX) or n.endswith(MAINLINE_SUFFIX)


def is_inbox_dir(name: str) -> bool:
    return (name or "").strip() in INBOX_ALIASES


def container_kind(name: str) -> str:
    """容器类型：inbox / series / mainline / album / plain。"""
    n = (name or "").strip()
    if is_inbox_dir(n):
        return "inbox"
    if n.endswith(SERIES_SUFFIX):
        return "series"
    if n.endswith(MAINLINE_SUFFIX):
        return "mainline"
    if n == "专辑":
        return "album"
    if n == "合集":
        return "container"
    return ""


def series_dir_name(series: str) -> str:
    """系列容器目录名：{系列名}（系列）。已带后缀则原样返回。"""
    s = (series or "").strip()
    for suf in (SERIES_SUFFIX, MAINLINE_SUFFIX):
        if s.endswith(suf):
            return s
    return s + SERIES_SUFFIX


def canonical_artwork(kind: str) -> str:
    """artwork 关键字归一：logo→clearlogo、backdrop→fanart。"""
    k = (kind or "").strip().lower()
    return ARTWORK_ALIASES.get(k, k)


def artwork_name(kind: str, media_stem: str = "") -> str:
    """artwork 文件名。

    media_stem 非空 → 前缀式（电影规范）：`{主文件主体}-poster.jpg`
    media_stem 为空 → 无前缀式（剧集规范）：`poster.jpg`
    """
    k = canonical_artwork(kind)
    ext = ARTWORK_EXTS.get(k, ".jpg")
    if media_stem:
        return f"{media_stem}-{k}{ext}"
    return f"{k}{ext}"


def season_poster_name(season: int) -> str:
    return SEASON_POSTER_FMT.format(s=season)


def parse_artwork(fname: str) -> str:
    """从文件名判断 artwork 关键字（含别名/前缀式/季海报）；不是 artwork 返回 ""。

    可识别：poster.jpg / -poster.jpg / logo.png / xxx-clearlogo.png /
            season01-poster.jpg / backdrop.jpg
    """
    if "." not in fname:
        return ""
    stem, _ext = fname.rsplit(".", 1)
    s = stem.strip().lower()
    if not s:
        return ""
    if s in ARTWORK_EXTS:
        return canonical_artwork(s)
    if s in ARTWORK_ALIASES:
        return canonical_artwork(s)
    # 季海报 season01-poster
    if s.startswith("season") and s.endswith("-poster"):
        return "season-poster"
    if "-" in s:
        tail = s.rsplit("-", 1)[1]
        if tail in ARTWORK_EXTS or tail in ARTWORK_ALIASES:
            return canonical_artwork(tail)
    return ""


# ── 多版本 / 多碟 识别 ───────────────────────────────────────
# 碟号尾巴：DISC1 / CD2 / Part3 / D4 / P5
DISC_TAIL_RE = re.compile(r"^[\s._\-]*(?:disc|cd|part|pt|d|p)\s*\d+$", re.IGNORECASE)


def media_stems(media_names: list[str]) -> list[str]:
    """媒体文件名 → 去扩展名的 stem 列表（保持顺序，去重）。"""
    out: list[str] = []
    for n in media_names:
        if not n or "." not in n:
            continue
        s = n.rsplit(".", 1)[0]
        if s and s not in out:
            out.append(s)
    return out


def is_same_version(stems: list[str]) -> bool:
    """多个 stem 是否属于**同一版本**（仅差碟号/分卷号）。

    是 → 公共前缀即 artwork 前缀（存量 `… Atmos DISC1.iso` / `DISC2.iso`）。
    否 → 是**多版本共存**（如 1080p + 2160p），各版本自成一套 artwork。
    """
    stems = [s for s in stems if s]
    if len(stems) <= 1:
        return True
    base = common_stem(stems)
    return all(DISC_TAIL_RE.match(s[len(base):]) for s in stems)


def version_groups(stems: list[str]) -> list[list[str]]:
    """把媒体 stem 按**版本**归并成组：仅差碟号/分卷号的合为一组。

    指环王 `… Atmos DISC1` + `… Atmos DISC2` → 1 组（1 个版本 / 2 张碟）
    007 `… 1080p AC3` + `… 2160p DTSHD-MA`   → 2 组（2 个版本）
    """
    groups: list[list[str]] = []
    for s in (x for x in stems if x):
        for g in groups:
            if is_same_version(g + [s]):
                g.append(s)
                break
        else:
            groups.append([s])
    return groups


def count_versions(stems: list[str]) -> int:
    """真实版本数（同版本多碟/多分卷只算 1）。

    与 `len(stems)` 的区别：后者是「不同文件主干数」，多碟作品会被多算。
    """
    return len(version_groups(stems))


def stem_candidates(stems: list[str]) -> list[str]:
    """媒体 stem 的合法 artwork 前缀候选集。

    同一版本时额外纳入**公共前缀** —— 存量多碟作品的 artwork/nfo 就是用它：
        `… 2160p TrueHD Atmos DISC1.iso` + `DISC2.iso`
        → 前缀 `… 2160p TrueHD Atmos`（不带碟号）
    """
    out = [s for s in stems if s]
    if out and is_same_version(out):
        base = common_stem(out)
        if base and base not in out:
            out.append(base)
    return out


def artwork_owner(fname: str, stems: list[str]) -> str:
    """该 artwork 文件归属哪个媒体前缀（最长匹配）；无前缀式返回 ""。

    存量样本：
        `… 1080p DTSHD-MA-poster.jpg` 属于 stem `… 1080p DTSHD-MA`
        `… 2160p TrueHD Atmos-poster.jpg` 属于多碟公共前缀 `… 2160p TrueHD Atmos`
        `poster.jpg`（无前缀式）→ ""
    """
    kind = parse_artwork(fname)
    if not kind or kind == "season-poster" or "." not in fname:
        return ""
    stem_part = fname.rsplit(".", 1)[0]
    cands = [st for st in stem_candidates(stems) if stem_part.startswith(st + "-")]
    if not cands:
        return ""
    return max(cands, key=len)


def is_unprefixed_artwork(fname: str) -> bool:
    """是否为无前缀式 artwork（`poster.jpg` / `backdrop.jpg`）——电影规范里不允许。"""
    if "." not in fname:
        return False
    s = fname.rsplit(".", 1)[0].strip().lower()
    return s in ARTWORK_EXTS or s in ARTWORK_ALIASES


def nfo_owner(fname: str, stems: list[str]) -> str:
    """该 nfo 文件是否与某个媒体前缀同名（电影规范）。返回匹配前缀或 ""。"""
    if not fname.lower().endswith(".nfo"):
        return ""
    s = fname[:-4]
    return s if s in stem_candidates(stems) else ""


def normalize_artwork_name(fname: str, media_stem: str = "") -> str:
    """把旧式/别名 artwork 文件名归一为规范名。

    media_stem 非空 → 前缀式（电影）；为空 → 无前缀式（剧集）。
    无法识别的文件原样返回。
    """
    if "." not in fname:
        return fname
    ext = fname.rsplit(".", 1)[1]
    kind = parse_artwork(fname)
    if not kind:
        return fname
    if kind == "season-poster":
        return fname
    if kind not in ARTWORK_EXTS:
        return fname  # banner/clearart 等保留原关键字
    if media_stem:
        return artwork_name(kind, media_stem)
    return f"{kind}.{ext if ext else ARTWORK_EXTS[kind].lstrip('.')}"


def normalize_nfo_name(fname: str, media_type: str, media_stem: str = "") -> str:
    """归一 nfo 名：电影优先与主文件同名；剧集固定 tvshow.nfo。"""
    if not fname.lower().endswith(".nfo"):
        return fname
    return nfo_name(media_type, media_stem)


def nfo_name(media_type: str, media_stem: str = "") -> str:
    """NFO 文件名：剧集固定 tvshow.nfo；电影优先与主文件同名。"""
    if media_type == "tv":
        return TV_NFO
    if media_stem:
        return f"{media_stem}.nfo"
    return MOVIE_NFO


def common_stem(stems: list[str]) -> str:
    """多主文件（DISC1/DISC2、CD1/CD2、Part1/Part2…）的**公共前缀**，用作 artwork 前缀。

    存量实例：
        「指环王1：护戒使者…2160p TrueHD Atmos DISC1.iso」
        「指环王1：护戒使者…2160p TrueHD Atmos DISC2.iso」
        → 前缀应为「指环王1：护戒使者…2160p TrueHD Atmos」（不含 DISC1）

    单文件时直接返回其 stem。
    """
    stems = [s for s in stems if s]
    if not stems:
        return ""
    if len(stems) == 1:
        return stems[0]
    a, b = min(stems), max(stems)      # 字典序极值的公共前缀 == 全集合公共前缀
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    pre = a[:i]
    # 回退到最近的分隔边界，避免留下半边 token（"... Atmos DISC" → "... Atmos"）
    if pre and not pre.endswith((" ", "_", ".", "-", "]", ")")):
        cut = max(pre.rfind(" "), pre.rfind("_"), pre.rfind("."))
        if cut > 0:
            pre = pre[:cut]
    # 再清掉明显的碟号残留（Movie.CD1 / Movie-Part2 / Movie D3）
    pre = re.sub(r"[\s._\-]+(?:disc|cd|part|pt|d|p)\s*\d+$", "", pre, flags=re.IGNORECASE)
    return pre.rstrip(" ._-")


# ═════════════════════════════════════════════════════════════
# 已冻结条款（电影）—— 对用户「电影命名规则我比较满意了」的逐条书面固化
# ═════════════════════════════════════════════════════════════
# 这张表是 tests/check_spec.py 的对照清单：任何一条被改动，守门校验立刻 FAIL。
# 表里的模板**直接引用上面的常量**，所以不可能与代码本身漂移。
FROZEN_MOVIE_RULES: dict[str, str] = {
    "folder_template": MOVIE_FOLDER_TEMPLATE,
    "folder_sample": "大黄蜂 (2018) {tmdbid-424783}",
    "file_template": MOVIE_FILE_TEMPLATE,
    "file_sample": "大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso",
    "artwork_style": "prefix：{主文件主体}-poster.jpg / -fanart.jpg / -clearlogo.png",
    "artwork_keywords": "poster / fanart / clearlogo（是 clearlogo 不是 logo；是 fanart 不是 backdrop）",
    "nfo_style": "与主文件同名（不是 movie.nfo）",
    "subtitle_style": "{主文件主体}.zh-CN.srt / .en.srt（语言码点号分隔，Emby/Kodi 约定）",
    "tech_order": " → ".join(TECH_ORDER),
    "tech_sep": "技术段整体包方括号 […]（分辨率随段进括号）；段内空格分隔",
    "colon": "半角冒号 → ' - '；全角冒号「：」保留",
    "multi_version": "多版本各自成套 artwork/nfo；多碟/分卷取公共前缀",
    "id_placement": "ID 只出现在目录名，文件名不带 ID",
}


def spec_dict() -> dict:
    """供 MCP / 文档消费的规范化描述。"""
    return {
        "version": SPEC_VERSION,
        "frozen_at": SPEC_FROZEN_AT,
        "scope_status": dict(SCOPE_STATUS),
        "frozen_scopes": [k for k, v in SCOPE_STATUS.items() if v == "frozen"],
        "frozen_movie_rules": dict(FROZEN_MOVIE_RULES),
        "category_roots": CATEGORY_ROOTS,
        "movie_folder_template": MOVIE_FOLDER_TEMPLATE,
        "tv_folder_template": TV_FOLDER_TEMPLATE,
        "season_folder_template": SEASON_FOLDER_TEMPLATE,
        "movie_file_template": MOVIE_FILE_TEMPLATE,
        "tv_file_template": TV_FILE_TEMPLATE,
        "tech_order": list(TECH_ORDER),
        "tech_sep": TECH_SEP,
        "artwork_exts": ARTWORK_EXTS,
        "artwork_rule": {
            "movie": "前缀式：{主文件主体}-poster.jpg / -fanart.jpg / -clearlogo.png；nfo 与主文件同名",
            "tv": "无前缀式（剧集根目录）：poster.jpg / fanart.jpg / clearlogo.png / "
                  "season01-poster.jpg / tvshow.nfo",
        },
        "container_suffixes": [SERIES_SUFFIX, MAINLINE_SUFFIX],
        "fixed_containers": sorted(FIXED_CONTAINERS),
        "inbox": sorted(INBOX_ALIASES),
    }
