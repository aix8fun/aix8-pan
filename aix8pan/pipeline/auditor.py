"""库审计器：扫描作品目录，报告与命名规范的偏差（**只读**）

用途：把存量与「统一命名规范 v2」逐项比对，输出可执行的整改清单。
本模块绝不写任何东西 —— 只 list + parse。

检查项（code）：
  FOLDER_NO_ID       电影作品目录缺 {tmdbid-N} 标识
  FOLDER_ID_LEGACY   标识写法过时（{tmdb-N} → 应为 {tmdbid-N}）
  FOLDER_ID_POS      标识不在「年份」之后（目录名结构不符）
  FOLDER_NO_YEAR     目录名缺年份
  FOLDER_TITLE_GAP   标题与括号年份之间缺空格（小猪佩奇(2004)）
  FOLDER_HAS_TECH    目录名掺入技术信息（1080p/BluRay…）
  FOLDER_EXTRA_SEG   标题后多出版本修饰词（「… - IMAX」/「… - Theatrical Edition」）
  FOLDER_NO_CJK      标题段无中文（用了 TMDB 原名）
  FOLDER_TV_NO_ID    剧集目录缺 tmdbid 标识（v2.2 规范为必带）
  FILE_HAS_ID        媒体文件名带 {tmdbid-N} 标识（规范为不带，ID 只出现在目录名）
  FILE_NO_BRACKET    媒体文件技术标签未包方括号（v2.1 规范为 [2160p TrueHD Atmos]）
  FILE_NO_YEAR       媒体文件名缺年份
  FILE_TECH_ORDER    技术标签顺序不符合规范
  ART_MOVIE_UNPREFIXED  电影海报为无前缀式（规范为 {主文件主体}-poster.jpg）
  ART_LEGACY_KEYWORD    artowrk 关键字过时（logo.png → clearlogo.png / backdrop.jpg → fanart.jpg）
  ART_TV_PREFIXED       剧集根目录图片为前缀式（规范为无前缀固定名）
  NFO_MOVIE_GENERIC     电影 nfo 未与主文件同名
  NFO_MISSING           缺 nfo
  ART_MISSING           缺海报/背景图
"""
from __future__ import annotations

import re

from ..core import naming_spec as spec
from ..config import load_config
from ..core.naming import NamingEngine
from ..core.openlist import OpenListClient
from ..core.parser import IMAGE_EXTS, QUALITY_TOKEN_RE, parse_media_name
from .planner import SEASON_DIR_RE

TMDB_ANY_RE = re.compile(r"\{\s*(tmdbid|tmdb)\s*-\s*(\d+)\s*\}", re.IGNORECASE)
# v2.1：技术段应整体包在 [...] 里；把方括号段抹掉后仍残留技术 token = 未按规范包裹
BRACKET_SPAN_RE = re.compile(r"\[[^\]]*\]")

SEV_ERROR = "error"
SEV_WARN = "warn"
SEV_INFO = "info"

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 「中文标题 - 拉丁修饰词」结尾：如「碟中谍6：全面瓦解 - IMAX」
LATIN_TAIL_RE = re.compile(r"\s+-\s+([A-Za-z][A-Za-z0-9 .]{1,30})$")


def title_segment_issues(folder: str, year: str) -> list[dict]:
    """只检查目录名「年份之前」的标题段形状（纯字符串，无需联网）。

    与 `_audit_work` 共用，保证离线补检与在线审计结论一致。
    """
    out: list[dict] = []
    if not year or not folder:
        return out
    title_seg = re.sub(r"\{[^}]*\}", "", folder.split(f"({year})")[0]).strip()
    if not title_seg:
        return out
    if not CJK_RE.search(title_seg):
        out.append({"code": "FOLDER_NO_CJK", "level": SEV_WARN,
                    "detail": f"标题段无中文：{title_seg}",
                    "suggestion": "目录名标题应为中文名（TMDB 无中文名时可用原名）"})
    ex = LATIN_TAIL_RE.search(title_seg)
    if ex and CJK_RE.search(title_seg[:ex.start()]):
        out.append({"code": "FOLDER_EXTRA_SEG", "level": SEV_WARN,
                    "detail": f"标题后多出版本修饰词：{ex.group(1)}",
                    "suggestion": f"目录名应为「{title_seg[:ex.start()].strip()} ({year}) …」，"
                                  f"版本信息（IMAX/导剪/剧场版）不进目录名"})
    return out


class Auditor:
    def __init__(self, cfg: dict | None = None, client: OpenListClient | None = None):
        self.cfg = cfg or load_config()
        ol = self.cfg["openlist"]
        self.client = client or OpenListClient(
            ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
        self.naming = NamingEngine(self.cfg.get("naming") or {})

    # ---------- 对外 ----------

    def audit(self, root: str, media_type: str = "auto",
              include_containers: bool = True, max_depth: int = 6) -> dict:
        """审计 root 下的全部作品目录。media_type: movie/tv/auto。"""
        works = self._find_works(root, include_containers, max_depth)
        result = {
            "root": root, "media_type": media_type,
            "works": len(works), "ok": 0,
            "issues": [], "by_code": {}, "summary": {},
        }
        for w in works:
            kind = self._kind(w, media_type)
            issues = self._audit_work(w, kind)
            if issues:
                result["issues"].append({"path": w, "kind": kind, "issues": issues})
                for it in issues:
                    result["by_code"][it["code"]] = result["by_code"].get(it["code"], 0) + 1
            else:
                result["ok"] += 1
        result["summary"] = {
            "works": result["works"], "ok": result["ok"],
            "nonconforming": len(result["issues"]),
            "errors": sum(1 for w in result["issues"] for i in w["issues"] if i["level"] == SEV_ERROR),
            "warns": sum(1 for w in result["issues"] for i in w["issues"] if i["level"] == SEV_WARN),
        }
        return result

    # ---------- 扫描 ----------

    def _find_works(self, root: str, include_containers: bool, max_depth: int) -> list[str]:
        """找作品目录。

        作品目录 = 直接含媒体文件，**或**含 Season* 子目录（剧集），且自身不是容器命名。
        季目录本身**不是**作品 —— 它的文件归属其父剧集目录。

        ⚠️ 每一层都用 refresh=True 强刷：OpenList 对 115 的目录列表会返回陈旧缓存，
        曾导致拿到「已不存在的目录名」（如 `终结者2：审判日 - Theatrical Edition`），
        进而产出假的偏差报告。
        """
        out: list[str] = []

        def walk(path: str, depth: int) -> None:
            if depth > max_depth:
                return
            name = path.rstrip("/").split("/")[-1]
            if SEASON_DIR_RE.match(name):
                return                       # 季目录由父剧集统一审计
            try:
                children = self.client.list_all(path, refresh=True)
            except Exception:
                return
            has_media = any(parse_media_name(c.get("name") or "").is_media
                            for c in children if not c.get("is_dir"))
            has_season = any(c.get("is_dir") and SEASON_DIR_RE.match(c.get("name") or "")
                             for c in children)
            is_container = spec.is_container_dir(name)
            if (has_media or has_season) and not is_container:
                out.append(path)
                return
            if not include_containers and is_container:
                return
            for c in children:
                if c.get("is_dir"):
                    walk(f"{path.rstrip('/')}/{c['name']}", depth + 1)

        walk(root, 1)
        return out

    def _kind(self, work: str, media_type: str) -> str:
        if media_type in ("movie", "tv"):
            return media_type
        try:
            entries = self.client.list_all(work, refresh=True)
        except Exception:
            return "movie"
        for e in entries:
            n = (e.get("name") or "").lower()
            if e.get("is_dir") and SEASON_DIR_RE.match(n):
                return "tv"
            if n == spec.TV_NFO:
                return "tv"
        for e in entries:
            if e.get("is_dir"):
                continue
            p = parse_media_name(e.get("name") or "")
            if p.is_media and (p.season is not None or p.episode is not None):
                return "tv"
        return "movie"

    # ---------- 单个作品 ----------

    def _audit_work(self, work: str, kind: str) -> list[dict]:
        issues: list[dict] = []
        entries = self.client.list_all(work, refresh=True)
        folder = work.rstrip("/").split("/")[-1]
        if spec.is_container_dir(folder):
            return issues

        def add(code, level, detail, suggestion=""):
            issues.append({"code": code, "level": level, "detail": detail,
                           "suggestion": suggestion})

        # ── 1. 目录名 ────────────────────────────────────────
        fp = parse_media_name(folder, is_dir=True)
        m = TMDB_ANY_RE.search(folder)
        if kind == "movie":
            if not m:
                add("FOLDER_NO_ID", SEV_ERROR, f"目录缺 tmdbid 标识：{folder}",
                    f"应形如「{fp.title or '标题'} ({fp.year or '年份'}) {{tmdbid-N}}」")
            elif m.group(1).lower() != "tmdbid":
                add("FOLDER_ID_LEGACY", SEV_ERROR,
                    f"标识写法过时 {{{m.group(1)}-{m.group(2)}}}",
                    f"改为 {{tmdbid-{m.group(2)}}}")
        else:
            if not m:
                add("FOLDER_TV_NO_ID", SEV_WARN, f"剧集目录缺 tmdbid 标识：{folder}",
                    f"应形如「{fp.title or '标题'} ({fp.year or '年份'}) {{tmdbid-N}}」（v2.2 起）")
            elif m.group(1).lower() != "tmdbid":
                add("FOLDER_ID_LEGACY", SEV_ERROR,
                    f"标识写法过时 {{{m.group(1)}-{m.group(2)}}}",
                    f"改为 {{tmdbid-{m.group(2)}}}")
        if not fp.year:
            add("FOLDER_NO_YEAR", SEV_ERROR, f"目录名缺年份：{folder}",
                "补 (年份)")
        else:
            # 标题与括号年份之间应有空格；标识应紧随年份之后
            idx = folder.find(f"({fp.year})")
            if idx > 0 and folder[idx - 1] not in " ":
                add("FOLDER_TITLE_GAP", SEV_WARN, f"标题与年份括号之间缺空格：{folder}",
                    f"改为「{folder[:idx]} ({folder[idx:]}」")
            rest = folder[idx + len(f"({fp.year})"):].strip()
            if rest and not TMDB_ANY_RE.fullmatch(rest):
                if QUALITY_TOKEN_RE.search(rest):
                    add("FOLDER_HAS_TECH", SEV_ERROR,
                        f"目录名掺入技术信息：{rest}", "技术信息只应出现在文件名")
                else:
                    add("FOLDER_ID_POS", SEV_WARN, f"年份之后有多余内容：{rest}",
                        "目录名结构应为「标题 (年份) {tmdbid-N}」")

            # ── 标题段本身的形状检查（年份**之前**）────────────
            for it in title_segment_issues(folder, fp.year):
                add(it["code"], it["level"], it["detail"], it["suggestion"])

        # ── 2. 文件（含季目录下钻）────────────────────────────
        files = [e for e in entries if not e.get("is_dir")]
        sub_dirs = [e for e in entries if e.get("is_dir")]
        media = []
        companions = []          # 仅作品根目录的伴随文件（artwork/nfo 角色检查只看这里）
        for e in files:
            p = parse_media_name(e.get("name") or "")
            (media if p.is_media else companions).append((e, p))
        for d in sub_dirs:
            if not SEASON_DIR_RE.match(d.get("name") or ""):
                continue
            try:
                sents = self.client.list_all(f"{work.rstrip('/')}/{d['name']}", refresh=True)
            except Exception:
                continue
            for e in sents:
                if e.get("is_dir"):
                    continue
                p = parse_media_name(e.get("name") or "")
                if p.is_media:
                    media.append((e, p))

        if not media:
            add("NO_MEDIA", SEV_WARN, "未找到媒体文件", "确认该目录是否为空壳")
            return issues

        for e, p in media:
            self._audit_media_name(issues, e["name"], p, kind)

        # ── 3. artwork / nfo ────────────────────────────────
        stems = spec.media_stems([e["name"] for e, _p in media])
        # 建议文案用的「代表前缀」：单版本取公共前缀（含多碟归并），多版本取主文件
        if len(stems) == 1:
            main_stem = stems[0]
        elif spec.is_same_version(stems):
            main_stem = spec.common_stem(stems)
        else:
            biggest = max(media, key=lambda ep: ep[0].get("size") or 0)
            main_stem = biggest[0]["name"].rsplit(".", 1)[0]
        self._audit_artwork(issues, companions, kind, stems, main_stem, bool(media))

        return issues

    def _audit_media_name(self, issues: list[dict], fname: str, p, kind: str) -> None:
        def add(code, level, detail, suggestion=""):
            issues.append({"code": code, "level": level, "detail": detail,
                           "suggestion": suggestion})

        if TMDB_ANY_RE.search(fname):
            add("FILE_HAS_ID", SEV_WARN, f"文件名带 ID 标识：{fname}",
                "ID 只出现在作品目录名，文件名不带")
        if kind == "movie" and p.tech:
            # v2.1：技术段必须整体包方括号；抹掉所有 [...] 段后还有技术 token = 未包裹
            outside = BRACKET_SPAN_RE.sub(" ", fname)
            if QUALITY_TOKEN_RE.search(outside):
                add("FILE_NO_BRACKET", SEV_WARN, f"技术标签未包方括号：{fname}",
                    "规范为 [2160p TrueHD Atmos]，分辨率随段进括号")
        if kind == "movie":
            if not p.year:
                add("FILE_NO_YEAR", SEV_ERROR, f"电影文件名缺年份：{fname}", "补 (年份)")
            else:
                from ..core.parser import extract_tech_fields, render_tech
                fields = extract_tech_fields(fname)
                canonical = render_tech(fields)
                if canonical and p.tech and canonical != p.tech:
                    add("FILE_TECH_ORDER", SEV_WARN,
                        f"技术标签顺序非规范：{p.tech} → 应为 {canonical}",
                        "顺序固定为 分辨率 片源 编码 HDR 音频 Atmos")

    def _audit_artwork(self, issues: list[dict], companions: list, kind: str,
                       stems: list[str], main_stem: str, has_media: bool) -> None:
        def add(code, level, detail, suggestion=""):
            issues.append({"code": code, "level": level, "detail": detail,
                           "suggestion": suggestion})

        names = [e.get("name") or "" for e, _ in companions]
        nfo_names = [n for n in names if n.lower().endswith(".nfo")]
        img_names = [n for n in names if n.rsplit(".", 1)[-1].lower() in
                     {x.lstrip(".") for x in IMAGE_EXTS}]

        # 关键字过时（logo→clearlogo / backdrop→fanart）
        for n in img_names:
            stem = n.rsplit(".", 1)[0].lower()
            tail = stem.rsplit("-", 1)[1] if "-" in stem else stem
            canon = spec.ARTWORK_ALIASES.get(tail)
            if canon and canon != tail and canon in spec.ARTWORK_EXTS:
                add("ART_LEGACY_KEYWORD", SEV_ERROR, f"artwork 关键字过时：{n}",
                    f"规范关键字为 {canon}"
                    f"（{spec.artwork_name(canon, main_stem if kind == 'movie' else '')}）")

        if kind == "movie":
            covered: set[str] = set()          # 已被「某个版本」承载的 artwork 关键字
            for n in img_names:
                owner = spec.artwork_owner(n, stems)
                if owner:
                    covered.add(spec.parse_artwork(n))
                elif spec.is_unprefixed_artwork(n):
                    k = spec.parse_artwork(n)
                    covered.add(k)
                    add("ART_MOVIE_UNPREFIXED", SEV_ERROR,
                        f"电影 artwork 为无前缀式：{n}",
                        f"改为前缀式 {spec.artwork_name(k, main_stem)}（前缀 = 对应主文件主体）")
            if has_media and stems:
                multi = not spec.is_same_version(stems)
                for k in ("poster", "fanart"):
                    if k in covered:
                        continue
                    add("ART_MISSING", SEV_WARN,
                        f"缺 {'海报 poster' if k == 'poster' else '背景图 fanart'}",
                        (f"每个版本都应带 {spec.artwork_name(k, '<主文件主体>')}"
                         if multi else f"应存在 {spec.artwork_name(k, main_stem)}"))
            # nfo：只要存在「与某主文件同名」的 nfo 即合规（多版本各自一套）
            if nfo_names:
                if not any(spec.nfo_owner(n, stems) for n in nfo_names):
                    add("NFO_MOVIE_GENERIC", SEV_WARN,
                        f"电影 nfo 未与主文件同名：{nfo_names[0]}",
                        f"改为 {spec.nfo_name('movie', main_stem)}")
            else:
                add("NFO_MISSING", SEV_INFO, "缺 nfo",
                    f"应存在 {spec.nfo_name('movie', main_stem)}")
        else:
            img_kinds = {spec.parse_artwork(n): n for n in img_names if spec.parse_artwork(n)}
            for k in ("poster", "fanart"):
                host = img_kinds.get(k, "")
                if host and "-" in host.rsplit(".", 1)[0]:
                    add("ART_TV_PREFIXED", SEV_ERROR, f"剧集根目录图片为前缀式：{host}",
                        f"剧集规范为无前缀固定名 {k}.jpg")
                elif not host:
                    add("ART_MISSING", SEV_WARN, f"缺 {k}.jpg", f"应存在 {k}.jpg")
            if nfo_names and spec.TV_NFO not in nfo_names:
                add("NFO_MOVIE_GENERIC", SEV_WARN, f"剧集 nfo 命名非规范：{nfo_names[0]}",
                    f"应为 {spec.TV_NFO}")
            elif not nfo_names:
                add("NFO_MISSING", SEV_INFO, "缺 nfo", f"应存在 {spec.TV_NFO}")
