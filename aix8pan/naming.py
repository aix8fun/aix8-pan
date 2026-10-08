"""命名引擎：三层命名模型渲染 + 非法字符规范化

模板变量（build_vars 产出）：
  {title}         中文标题
  {original}      原文标题（拉丁标题，非拉丁则为空）
  {year}          年份
  {season}        季号（整数）
  {season_ep}     S01E02
  {episode}       集号（整数）
  {tech}          规范顺序技术标签串（可能为空）
  {tmdbid_tag}    「{tmdbid-N}」（无 ID 则为空）
  {tmdb_id}       纯数字 ID
  {episode_title} 单集标题
  {episode_title_seg}  「 - 单集标题」（无则为空）

模板默认值全部取自 panbutler.naming_spec（单一事实源），本模块不再硬编码形态。
空值剔除：变量为空时连同相邻空白与包裹括号一起省略。
"""
from __future__ import annotations

import re

from . import naming_spec as spec

ILLEGAL_CHARS_RE = re.compile(r'[\\/*?"<>|]')
TRAILING_DOTSPACE_RE = re.compile(r"[ \.]+$")
MAX_NAME_BYTES = 235  # 网盘/文件系统安全上限（留余量）

# 存量实测：半角冒号 → " - "（ASCII 连字符 + 两侧空格）
#           全角冒号「：」**保留**（`变形金刚2：卷土重来` / `古墓丽影：源起之战`）
#           其余非法字符 → "-"
COLON_ASCII_RE = re.compile(r"\s*:\s*")
ILLEGAL_RE = re.compile(r'[\\/*?"<>|]')

# 模板变量名（供校验/文档）
TEMPLATE_VARS = (
    "title", "original", "year", "season", "episode", "season_ep",
    "tech", "tmdb_id", "tmdbid_tag", "episode_title", "episode_title_seg",
)


def sanitize(name: str) -> str:
    """规范化目录/文件名。

    - 半角冒号 `:` → ` - `（对齐存量 `Dune: Part Two` → `Dune - Part Two`）
    - 全角冒号 `：` 保留（对齐存量 `变形金刚2：卷土重来`）
    - 其它非法字符 `\\ / * ? " < > |` → `-`
    - 折叠空白、去首尾点与空格、限长 235 字节
    """
    name = COLON_ASCII_RE.sub(" - ", name)
    name = ILLEGAL_RE.sub("-", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = TRAILING_DOTSPACE_RE.sub("", name)
    name = name.strip(" .")
    if not name:
        name = "未命名"
    if len(name.encode("utf-8")) <= MAX_NAME_BYTES:
        return name
    # 超长：保留扩展名，按字节截断主体
    ext = ""
    dot = name.rfind(".")
    if dot > 0:
        ext = name[dot:]
    stem = name[:len(name) - len(ext)]
    while stem and len(stem.encode("utf-8")) + len(ext.encode()) > MAX_NAME_BYTES:
        stem = stem[:-1]
    stem = stem.rstrip(" .-—_")
    return stem + ext if stem else (name[:MAX_NAME_BYTES // 3])


class NamingEngine:
    def __init__(self, naming_cfg: dict | None = None):
        cfg = naming_cfg or {}
        shared_folder = cfg.get("folder_template") or ""
        self.movie_folder_tpl = (
            cfg.get("movie_folder_template") or shared_folder
            or spec.MOVIE_FOLDER_TEMPLATE)
        self.tv_folder_tpl = (
            cfg.get("tv_folder_template") or shared_folder
            or spec.TV_FOLDER_TEMPLATE)
        self.season_tpl = cfg.get("season_folder_template") or spec.SEASON_FOLDER_TEMPLATE
        self.movie_tpl = cfg.get("movie_file_template") or spec.MOVIE_FILE_TEMPLATE
        self.tv_tpl = cfg.get("tv_file_template") or spec.TV_FILE_TEMPLATE
        # 兼容：单一 folder_template 时按类型分别回落
        self.folder_tpl = shared_folder or self.movie_folder_tpl

    # ---------- 渲染 ----------

    _SEP = r"[-–—|·,、]"

    def _strip_empty(self, template: str, key: str) -> str:
        """值为空的变量：连同相邻分隔符/包裹括号从模板中删除。"""
        v = "{" + key + "}"
        t = re.sub(rf"[\(\[]\s*{re.escape(v)}\s*[\)\]]", "", template)
        t = re.sub(rf"\s*{self._SEP}\s*{re.escape(v)}", "", t)
        t = re.sub(rf"{re.escape(v)}\s*{self._SEP}\s*", "", t)
        t = t.replace(v, "")
        return t

    def _render(self, template: str, vars: dict) -> str:
        out = template
        for key, val in vars.items():
            if val in (None, ""):
                out = self._strip_empty(out, key)
            else:
                out = out.replace("{" + key + "}", str(val))
        # 剔除未被替换的变量（防御）与残留空括号
        out = re.sub(r"\{[a-z_]+(?::[^}]*)?\}", "", out)
        out = re.sub(r"\(\s*\)|\[\s*\]|【\s*】|《\s*》", "", out)
        # 首尾悬空分隔符
        out = re.sub(r"^\s*[-–—|·,、]\s*", "", out)
        out = re.sub(r"\s*[-–—|·,、]\s*$", "", out)
        out = re.sub(r"\s{2,}", " ", out)
        return out.strip()

    def build_vars(self, *, title: str, original: str = "", year: str = "",
                   season: int | None = None, episode: int | None = None,
                   tech: str = "", tmdb_id: str = "", episode_title: str = "") -> dict:
        season_ep = ""
        if season is not None and episode is not None:
            season_ep = f"S{season:02d}E{episode:02d}"
        tmdbid_tag = f"{{tmdbid-{tmdb_id}}}" if tmdb_id else ""
        episode_title_seg = f" - {episode_title}" if episode_title else ""
        return {
            "title": title or "",
            "original": original or "",
            "year": year or "",
            "season": season,
            "episode": episode,
            "season_ep": season_ep,
            "tech": tech or "",
            "tmdb_id": tmdb_id or "",
            "tmdbid_tag": tmdbid_tag,
            "episode_title": episode_title or "",
            "episode_title_seg": episode_title_seg,
        }

    # ---------- 作品目录 ----------

    def folder_name(self, v: dict, kind: str = "movie") -> str:
        """作品目录名。movie 带 {tmdbid-N}；tv 不带（对齐存量）。"""
        tpl = self.tv_folder_tpl if kind == "tv" else self.movie_folder_tpl
        return sanitize(self._render(tpl, v))

    def season_folder_name(self, season: int) -> str:
        return sanitize(self.season_tpl.format(season=season))

    # ---------- 作品文件 ----------

    def movie_file_name(self, v: dict, ext: str) -> str:
        # original 为空时模板中间会多空格，_render 已做清理
        return sanitize(self._render(self.movie_tpl, v)) + ext

    def tv_file_name(self, v: dict, ext: str) -> str:
        return sanitize(self._render(self.tv_tpl, v)) + ext

    # ---------- artwork 文件名（规范：单一事实源命名）----------

    @staticmethod
    def artwork_name(kind: str, media_stem: str = "") -> str:
        """电影传 media_stem → 前缀式；剧集不传 → 无前缀式。"""
        return spec.artwork_name(kind, media_stem)

    @staticmethod
    def season_poster_name(season: int) -> str:
        return spec.season_poster_name(season)

    @staticmethod
    def nfo_name(media_type: str, media_stem: str = "") -> str:
        return spec.nfo_name(media_type, media_stem)

    @staticmethod
    def is_artwork_name(fname: str) -> bool:
        """是否规范 artwork 名（前缀式或无前缀式）。"""
        stem = fname.rsplit(".", 1)[0].lower() if "." in fname else fname.lower()
        if stem in {k for k in spec.ARTWORK_EXTS}:
            return True
        if "-" in stem:
            return stem.rsplit("-", 1)[1] in {k for k in spec.ARTWORK_EXTS} \
                or stem.rsplit("-", 1)[1] in spec.ARTWORK_ALIASES
        return False


def latin_title(original: str) -> str:
    """原文标题是否为拉丁文字（决定电影文件是否拼英文名）。"""
    if not original:
        return ""
    letters = [ch for ch in original if ch.isalpha()]
    if not letters:
        return ""
    latin = sum(1 for ch in letters if ord(ch) < 0x2E80)
    return original if latin / len(letters) > 0.8 else ""
