"""刮削器：下载 TMDB 图片 + 生成 NFO 上传到作品目录

产物命名**严格**遵循 aix8pan.naming_spec（见 SPEC.md）：

- 电影（前缀式 / Plex-Kodi local artwork）：
    大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos-poster.jpg
    大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos-fanart.jpg
    大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos-clearlogo.png
    大黄蜂 Bumblebee (2018) 2160p TrueHD Atmos.nfo
  → 前缀 = 目录内主媒体文件（体积最大者）的完整 stem
  → 若目录内没有媒体文件，回落到目录级无前缀名（poster.jpg / movie.nfo）

- 剧集（无前缀式，放剧集根目录）：
    poster.jpg / fanart.jpg / clearlogo.png / season01-poster.jpg / tvshow.nfo

注意 `logo` 一律规范为 `clearlogo`（存量如此）。
已存在的文件默认跳过（**绝不覆盖用户已有的刮削**）；`force=True` 或 `force_nfo=True`
时才覆盖，且走「先删后传」—— 因为 115 的 PUT 对已存在文件是静默无操作。
`cleanup_legacy=True` 时会删掉与新建文件等价的**旧式无前缀电影图片**（poster.jpg 等），
完成形态归一。

⚠️ 库内现有 nfo 是 tMM 生成的**富信息版**（含完整 cast/crew，20–35 KB），
而本模块生成的是精简版（~1 KB）。**不要**对已有 nfo 用 force —— 那是信息降级。
"""
from __future__ import annotations

import html
import re
import urllib.request

from ..core import naming_spec as spec
from ..config import load_config
from ..core.openlist import OpenListClient, OpenListError
from ..core.tmdb import TMDBClient, norm_meta

# 旧式（无前缀）电影图片名 → 规范 artwork 关键字
_LEGACY_MOVIE_ART = {
    "poster.jpg": "poster", "poster.png": "poster",
    "fanart.jpg": "fanart", "fanart.png": "fanart", "backdrop.jpg": "fanart",
    "logo.png": "clearlogo", "clearlogo.png": "clearlogo",
}
_LEGACY_MOVIE_NFO = {"movie.nfo"}

# Season 目录名（Season 01 / S1 / 第1季 …）→ 季号
_SEASON_DIR_RE = re.compile(
    r"^(?:Season|S)\s*0*(\d{1,2})$|^第\s*0*(\d{1,2})\s*季$", re.IGNORECASE)


def _nfo_outdated(xml: str) -> bool:
    """tvshow.nfo 是否为旧工具生成的残缺版，需要重写。

    分类依据（2026-10-09 全库盘点结论）：
    - 含 <seasoncount> → 本项目模板（最新）
    - 含 <actor> / <credits> → tMM 富信息版（含演职员表，信息量更大，保留）
    - 两者皆无 → 旧工具残缺版（如 season=-1、以 imdb 为默认 ID），
      媒体库识别会错乱 → 重写。电影 nfo 不走此判定。
    """
    if "<seasoncount>" in xml:
        return False
    if "<actor" in xml or "<credits>" in xml:
        return False
    return True


class Scraper:
    def __init__(self, cfg: dict | None = None, client: OpenListClient | None = None,
                 tmdb: TMDBClient | None = None):
        self.cfg = cfg or load_config()
        ol = self.cfg["openlist"]
        self.client = client or OpenListClient(
            ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
        t = self.cfg["tmdb"]
        self.tmdb = tmdb or TMDBClient(
            t["api_key"], t["api_host"], t["image_host"], t["language"],
            t["request_interval_ms"])

    # ---------- 对外 ----------

    def scrape(self, work_dir: str, media_type: str = "auto",
               tmdb_id: str = "", force: bool = False,
               cleanup_legacy: bool = False, title_override: str = "",
               force_nfo: bool = False) -> dict:
        """刮削一个作品目录。

        media_type: movie/tv/auto（auto 时若目录下有 Season* 子目录或 SxxExx 文件则视为 tv）
        tmdb_id: 可选，已知 ID 直接用；否则按目录名（标题 (年份)）搜索。
        cleanup_legacy: 电影目录里旧式无前缀图片（poster.jpg/logo.png）在生成规范
                       前缀式图片后被删除，实现形态归一。
        title_override: TMDB 中文库缺译名时，用该标题写入 nfo 的 <title>（仅影响
                       nfo 文本，不改变 TMDB 检索结果）。
        force_nfo: 只强制重写 nfo（图片仍按「已存在则跳过」），用于目录改名后
                   刷新 nfo 里的标题。
        """
        entries = self.client.list_all(work_dir, refresh=True)
        names = [e.get("name") or "" for e in entries]
        kind = self._detect_kind(work_dir, entries, media_type)
        if not tmdb_id:
            folder = work_dir.rstrip("/").split("/")[-1]
            from ..core.parser import parse_media_name
            p = parse_media_name(folder, is_dir=True)
            title, year = p.title, p.year
            if not title:
                return {"ok": False, "error": f"无法从目录名解析标题: {folder}"}
            m = self.tmdb.match(title, year, kind)
            if not m:
                return {"ok": False, "error": f"TMDB 未匹配: {title} ({year})"}
            tmdb_id = m["id"]

        detail = self.tmdb.detail(tmdb_id, kind)
        meta = norm_meta(detail, kind)
        if title_override:
            meta = dict(meta, title=title_override)

        # 前缀来源：电影 → 主媒体文件 stem；剧集 → 无前缀
        media_stem = "" if kind == "tv" else self._main_media_stem(entries)

        uploaded: list[str] = []
        skipped: list[str] = []
        removed: list[str] = []
        names_lower = {n.lower(): n for n in names}

        def put(remote_name: str, content: bytes, force_now: bool = False):
            remote = f"{work_dir.rstrip('/')}/{remote_name}"
            can_replace = force or force_now
            if not can_replace and remote_name in names:
                skipped.append(remote_name)
                return
            # 115 的 PUT 无法覆盖已存在文件（返回成功但内容不变）→ 先删后传
            self.client.upload(remote, content, overwrite=can_replace and remote_name in names)
            uploaded.append(remote_name)

        def put_art(kind_key: str, path: str):
            try:
                put(spec.artwork_name(kind_key, media_stem),
                    self.tmdb.download_image(path))
            except Exception as ex:
                skipped.append(f"{spec.artwork_name(kind_key, media_stem)} (下载失败: {ex})")

        if meta.get("poster_path"):
            put_art("poster", meta["poster_path"])
        if meta.get("backdrop_path"):
            put_art("fanart", meta["backdrop_path"])
        if meta.get("logo_path"):
            put_art("clearlogo", meta["logo_path"])

        # NFO：电影与主文件同名；剧集 tvshow.nfo
        # 剧集：已存在的 tvshow.nfo 若是旧工具残缺版（无 seasoncount 也无
        # 演职员表）→ 自动重写为项目模板；tMM 富信息版保留（信息不降级）
        force_rewrite = False
        nfo_name = spec.nfo_name(kind, media_stem)
        if kind == "tv" and nfo_name in names and not (force or force_nfo):
            try:
                link = self.client.get_download_url(f"{work_dir.rstrip('/')}/{nfo_name}")
                xml = urllib.request.urlopen(link, timeout=60).read().decode("utf-8", "replace")
                force_rewrite = _nfo_outdated(xml)
            except Exception:
                pass  # 下载失败 → 按老规矩「已存在则跳过」
        put(nfo_name, self._build_nfo(meta, kind).encode("utf-8"),
            force_now=force_nfo or force_rewrite)

        # 剧集：季海报（放剧集根目录，seasonNN-poster.jpg）
        # 只刮**本地实际存在**的季 —— TMDB 可能把续作并成同剧的 S2
        # （如 步步惊心 S2 实为《步步惊情》），本地没有的季不上海报。
        # 本地一季都识别不到时（目录还没整理）回落为全量，保持旧行为。
        if kind == "tv":
            local_seasons = self._local_seasons(entries)
            for s in meta.get("seasons") or []:
                if not s.get("poster_path"):
                    continue
                if local_seasons and s["season"] not in local_seasons:
                    skipped.append(f"{spec.season_poster_name(s['season'])} (本地无此季)")
                    continue
                sname = spec.season_poster_name(s["season"])
                try:
                    put(sname, self.tmdb.download_image(s["poster_path"]))
                except Exception as ex:
                    skipped.append(f"{sname} (下载失败: {ex})")

        # 电影：清理旧式无前缀图片 / movie.nfo（形态归一）
        if kind == "movie" and cleanup_legacy and media_stem:
            want = {spec.artwork_name(k, media_stem) for k in spec.ARTWORK_EXTS}
            want.add(spec.nfo_name("movie", media_stem))
            for legacy, kind_key in _LEGACY_MOVIE_ART.items():
                actual = names_lower.get(legacy)
                if not actual:
                    continue
                canon = spec.artwork_name(kind_key, media_stem)
                if canon in want and canon != actual:
                    try:
                        self.client.remove(work_dir, [actual])
                        removed.append(actual)
                    except OpenListError as ex:
                        skipped.append(f"{actual} (旧式文件删除失败: {ex})")
            for legacy in _LEGACY_MOVIE_NFO:
                actual = names_lower.get(legacy)
                if actual and actual not in want:
                    try:
                        self.client.remove(work_dir, [actual])
                        removed.append(actual)
                    except OpenListError as ex:
                        skipped.append(f"{actual} (旧式文件删除失败: {ex})")

        return {
            "ok": True, "kind": kind, "tmdb_id": tmdb_id,
            "title": meta["title"], "year": meta["year"],
            "media_stem": media_stem,
            "uploaded": uploaded, "skipped": skipped, "removed": removed,
        }

    # ---------- 内部 ----------

    @staticmethod
    def _local_seasons(entries: list[dict]) -> set[int]:
        """本地实际存在的季号：Season 目录名 + 散落剧集文件的 SxxExx 令牌。

        list_all 只列单层，季目录内的集文件不可见，因此主要靠目录名识别；
        集文件直接散放在作品根目录（未整理）时由 SxxExx 令牌兜底。
        """
        from ..core.parser import parse_media_name
        seasons: set[int] = set()
        for e in entries:
            n = (e.get("name") or "").strip()
            if e.get("is_dir"):
                m = _SEASON_DIR_RE.match(n)
                if m:
                    seasons.add(int(m.group(1) or m.group(2)))
            else:
                p = parse_media_name(n)
                if p.season is not None:
                    seasons.add(p.season)
        return seasons

    @staticmethod
    def _main_media_stem(entries: list[dict]) -> str:
        """作品内主文件前缀 —— 作为电影 artwork/nfo 前缀。

        单文件 → 其完整 stem；多碟（DISC1/DISC2）→ 去掉碟号后的公共部分，
        与存量「…2160p TrueHD Atmos-poster.jpg」一致；
        **多版本共存**（1080p + 2160p）→ 取体积最大版本（不合并成公共前缀，
        否则会造出一个不存在版本的前缀名）。
        """
        from ..core.parser import parse_media_name
        stems = []
        biggest, biggest_size = "", -1
        for e in entries:
            if e.get("is_dir"):
                continue
            n = e.get("name") or ""
            if not parse_media_name(n).is_media:
                continue
            if "." in n:
                stems.append(n.rsplit(".", 1)[0])
                sz = e.get("size") or 0
                if sz >= biggest_size:
                    biggest, biggest_size = n.rsplit(".", 1)[0], sz
        stems = [s for s in stems if s]
        if not stems:
            return ""
        if spec.is_same_version(stems):
            return spec.common_stem(stems)
        return biggest

    def _detect_kind(self, work_dir: str, entries: list[dict], media_type: str) -> str:
        if media_type in ("movie", "tv"):
            return media_type
        for e in entries:
            n = (e.get("name") or "").lower()
            if n.startswith("season"):
                return "tv"
            if n in ("tvshow.nfo",):
                return "tv"
        from ..core.parser import parse_media_name
        for e in entries:
            if e.get("is_dir"):
                continue
            p = parse_media_name(e.get("name") or "")
            if p.is_media and (p.season is not None or p.episode is not None):
                return "tv"
        return "movie"

    def _build_nfo(self, meta: dict, kind: str) -> str:
        e = html.escape
        rating = meta.get("rating") or 0
        if kind == "movie":
            return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>{e(meta['title'])}</title>
  <originaltitle>{e(meta.get('original_title') or '')}</originaltitle>
  <year>{e(meta.get('year') or '')}</year>
  <uniqueid type="tmdb" default="true">{e(meta['id'])}</uniqueid>
  <ratings><rating name="tmdb" max="10" default="true"><value>{rating:.1f}</value><votes>0</votes></rating></ratings>
  <plot>{e(meta.get('overview') or '')}</plot>
  <runtime>{meta.get('runtime') or 0}</runtime>
  {''.join(f'<genre>{e(g)}</genre>' for g in meta.get('genres') or [])}
  <tmdbid>{e(meta['id'])}</tmdbid>
</movie>
"""
        seasons_xml = "\n".join(
            f"  <season number=\"{s['season']}\" name=\"{e(s.get('name') or '')}\" "
            f"aired=\"{e(s.get('air_date') or '')}\" episodeCount=\"{s.get('episode_count') or 0}\"/>"
            for s in meta.get("seasons") or [])
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<tvshow>
  <title>{e(meta['title'])}</title>
  <originaltitle>{e(meta.get('original_title') or '')}</originaltitle>
  <year>{e(meta.get('year') or '')}</year>
  <uniqueid type="tmdb" default="true">{e(meta['id'])}</uniqueid>
  <ratings><rating name="tmdb" max="10" default="true"><value>{rating:.1f}</value><votes>0</votes></rating></ratings>
  <plot>{e(meta.get('overview') or '')}</plot>
{''.join(f'  <genre>{e(g)}</genre>' for g in meta.get('genres') or [])}
  <tmdbid>{e(meta['id'])}</tmdbid>
  <seasoncount>{meta.get('number_of_seasons') or 0}</seasoncount>
{seasons_xml}
</tvshow>
"""
