"""规划器：只读扫描 → 解析 → TMDB 匹配 → 生成整理 Plan JSON

铁律：本模块绝不执行任何写操作。Plan 生成后落盘，由 executor 在用户确认后执行。

Plan 结构：
{
  "plan_id": "...", "created_at": "...", "status": "draft|executed|failed|partial",
  "source": "...", "target_root": "...", "media_type": "movie|tv|mixed",
  "groups": [ { 标题/年份/tmdb/动作列表 } ],
  "actions": [ {action, ...} ],   # 扁平动作序列（executor 直接消费）
  "skips": [ {name, reason} ],
  "unmatched": [ {name, guess_title, guess_year, reason} ],
  "summary": {...}
}
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from .config import PLANS_DIR, load_config
from . import naming_spec as spec
from .naming import NamingEngine, latin_title
from .openlist import OpenListClient
from .parser import (
    IMAGE_EXTS, ParsedName, looks_organized_folder, parse_media_name, season_folder_name,
    violates_filename_spec,
)

SEASON_DIR_RE = re.compile(r"^(?:Season|S)\s*\d{1,2}$|^第\s*\d{1,2}\s*季$", re.IGNORECASE)
# 旧式 TMDB 标识写法（{tmdb-N}），规范应为 {tmdbid-N}
LEGACY_TMDB_TAG_RE = re.compile(r"\{\s*tmdb\s*-\s*(\d+)\s*\}", re.IGNORECASE)
from .tmdb import TMDBClient, norm_meta


class Planner:
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
        self.naming = NamingEngine(self.cfg.get("naming") or {})
        self.paths = self.cfg.get("paths") or {}

    # ---------- 对外主入口 ----------

    def build_plan(self, source: str, target_root: str | None = None,
                   media_type: str = "auto", dry_title: str = "",
                   include_containers: bool = False,
                   drain_inbox: bool = True,
                   normalize_artwork: bool = True,
                   normalize_names: bool = True,
                   canonical_folder: bool = False,
                   title_override: str = "",
                   use_tmdb_title: bool = False) -> dict:
        """扫描 source（一个待整理目录），生成整理 Plan。

        source 下每个子目录视为一个「作品组」；直接散落的媒体文件视为一组。

        组织容器（合集 / 专辑 / （系列） / （主线））**默认不动**，只记一条 skip；
        include_containers=True 时递归下钻到容器内部找作品目录。
        收件箱（0-待整理 / 待整理）默认「排空」——把里面的作品搬进目标库。

        canonical_folder=True 时**强制**按模板重算作品目录名（忽略「源目录名看着已合规」
        与「目标库已有同作品目录」两条复用捷径），用于把存量里明确违规的目录名一次纠正
        （多余版本修饰词 / 旧式标识 / 缺 ID 标识）。
        use_tmdb_title=True 时标题改用 TMDB 官方标题（默认「信任存量」取目录名标题），
        用于纠正目录名标题与 TMDB 的明确偏差。
        title_override 用于 TMDB 中文库缺译名时的手工指定标题（优先级最高）。
        """
        target_root = target_root or self._default_target(media_type)
        entries = self.client.list_all(source, refresh=True)
        all_dirs = [e for e in entries if e.get("is_dir")]
        files = [e for e in entries if not e.get("is_dir")]
        season_dirs = [d for d in all_dirs if SEASON_DIR_RE.match(d.get("name") or "")]

        work_dirs: list[dict] = []
        inbox_dirs: list[dict] = []
        container_dirs: list[dict] = []
        for d in all_dirs:
            n = d.get("name") or ""
            if SEASON_DIR_RE.match(n):
                continue
            if spec.is_inbox_dir(n):
                inbox_dirs.append(d)
            elif spec.is_container_dir(n):
                container_dirs.append(d)
            else:
                work_dirs.append(d)

        plan = {
            "plan_id": f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "draft",
            "source": source,
            "target_root": target_root,
            "media_type": media_type,
            "groups": [],
            "actions": [],
            "skips": [],
            "unmatched": [],
            "summary": {},
        }

        # ① 组织容器：默认只报告不动
        if container_dirs and not include_containers:
            for d in container_dirs:
                kind = spec.container_kind(d["name"]) or "container"
                plan["skips"].append({
                    "name": d["name"],
                    "reason": f"组织容器（{kind}），不参与整理；"
                              f"如需处理请直接指定其内部作品路径"})

        # ② 收件箱排空
        if drain_inbox:
            for d in inbox_dirs:
                sub = f"{source.rstrip('/')}/{d['name']}"
                for wd in self._collect_work_dirs(sub, refresh=True):
                    work_dirs.append({"name": wd, "_full": wd})
        if inbox_dirs and not drain_inbox:
            for d in inbox_dirs:
                plan["skips"].append({"name": d["name"], "reason": "收件箱（未启用排空）"})

        # ③ 容器下钻（可选）
        if include_containers:
            for d in container_dirs:
                sub = f"{source.rstrip('/')}/{d['name']}"
                for wd in self._collect_work_dirs(sub, refresh=True):
                    work_dirs.append({"name": wd, "_full": wd})

        for d in work_dirs:
            full = d.get("_full") or f"{source.rstrip('/')}/{d['name']}"
            self._plan_group(plan, full, target_root, media_type,
                             normalize_artwork=normalize_artwork,
                             normalize_names=normalize_names,
                             canonical_folder=canonical_folder,
                             title_override=title_override,
                             use_tmdb_title=use_tmdb_title)

        if files or season_dirs:
            # 源目录本身就是一个作品（散落文件 / 按 Season 分目录的剧集）
            self._plan_group(plan, source, target_root, media_type, entries=entries,
                             normalize_artwork=normalize_artwork,
                             normalize_names=normalize_names,
                             canonical_folder=canonical_folder,
                             title_override=title_override,
                             use_tmdb_title=use_tmdb_title)

        self._finalize(plan)
        return plan

    def save_plan(self, plan: dict) -> Path:
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        p = PLANS_DIR / f"{plan['plan_id']}.json"
        p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def load_plan(self, plan_id: str) -> dict:
        p = PLANS_DIR / f"{plan_id}.json"
        if not p.exists():
            raise FileNotFoundError(f"Plan 不存在: {plan_id}")
        return json.loads(p.read_text(encoding="utf-8"))

    def update_plan(self, plan: dict) -> None:
        p = PLANS_DIR / f"{plan['plan_id']}.json"
        p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 内部 ----------

    def _default_target(self, media_type: str) -> str:
        if media_type == "tv":
            return self.paths.get("tv", "/115/02-剧集")
        if media_type == "anime":
            return self.paths.get("anime", "/115/03-动画")
        return self.paths.get("movies", "/115/01-电影")

    def _collect_work_dirs(self, root: str, refresh: bool = False,
                           max_depth: int = 6) -> list[str]:
        """递归找「作品目录」——直接含媒体文件的目录；容器名目录不算作品。

        用于容器（合集/专辑/（系列）/（主线）/收件箱）下钻。
        """
        out: list[str] = []

        def walk(path: str, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                children = self.client.list_all(path, refresh=refresh and depth == 1)
            except Exception:
                return
            has_media = any(
                parse_media_name(c.get("name") or "").is_media
                for c in children if not c.get("is_dir"))
            if has_media and not spec.is_container_dir(path.rstrip("/").split("/")[-1]):
                out.append(path)
                return
            for c in children:
                if c.get("is_dir"):
                    walk(f"{path.rstrip('/')}/{c['name']}", depth + 1)

        walk(root, 1)
        return out

    def _plan_group(self, plan: dict, group_dir: str, target_root: str,
                    media_type: str, entries: list[dict] | None = None,
                    normalize_artwork: bool = True, normalize_names: bool = True,
                    canonical_folder: bool = False, title_override: str = "",
                    use_tmdb_title: bool = False):
        """处理一个作品组（group_dir 目录本身或给定的文件列表）。"""
        if entries is None:
            entries = self.client.list_all(group_dir, refresh=True)
        media = []
        companions = []
        others = []
        for e in entries:
            name = e.get("name") or ""
            p = parse_media_name(name)
            if p.is_media:
                media.append((e, p))
            elif p.is_companion or p.ext in (".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx") \
                    or p.ext in IMAGE_EXTS:
                companions.append((e, p))
            elif e.get("is_dir") and SEASON_DIR_RE.match(name):
                # 下钻 Season XX 子目录（剧集存量标准结构），并记住其真实目录名
                sub = f"{group_dir.rstrip('/')}/{name}"
                for se in self.client.list_all(sub, refresh=True):
                    sn = se.get("name") or ""
                    sp = parse_media_name(sn)
                    se = dict(se, _dir=sub, _dir_name=name, _season_dir_name=name)
                    if sp.is_media:
                        media.append((se, sp))
                    elif sp.is_companion or sp.ext in (".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx", ".jpg", ".png"):
                        companions.append((se, sp))
                    else:
                        others.append((se, sp))
            else:
                others.append((e, p))

        if not media:
            for e, _ in others:
                plan["skips"].append({"name": e["name"], "reason": "目录中无媒体文件"})
            return
        # 无法归类且与整理无关的文件：不生成动作（保持原位）；若整组目录整体搬移
        # 则它们会随目录一起移动，无需单独处理。
        for e, _ in others:
            plan["skips"].append({"name": e["name"],
                                  "reason": f"非媒体/非伴随文件，不单独处理（{group_dir}）"})

        # 作品身份识别（「信任存量」优先级）：
        #   ① 目录自带 {tmdb-N}/{tmdbid-N} 标识 → 直接信它，标题年份取目录名
        #   ② 目录名已含「标题 (年份)」 → 标题年份取目录名，TMDB 仅补 ID/原名
        #   ③ 否则退回用文件解析结果，再 TMDB 匹配
        def score(p: ParsedName) -> int:
            return (2 if p.year else 0) + (2 if p.season is not None and p.episode is not None
                                           else 1 if p.episode else 0)

        folder_raw = group_dir.rstrip("/").split("/")[-1]
        folder_parsed = parse_media_name(folder_raw, is_dir=True)
        is_tv = (media_type == "tv" or
                 (media_type == "auto" and any(
                     p.season is not None or p.episode is not None for _, p in media)))
        kind = "tv" if is_tv else "movie"

        meta = None
        title = year = tmdb_id = ""
        if folder_parsed.tmdb_id:
            tmdb_id = folder_parsed.tmdb_id
            title = folder_parsed.title
            year = folder_parsed.year
            if self.tmdb.available:
                try:
                    meta = norm_meta(self.tmdb.detail(tmdb_id, kind), kind)
                except Exception:
                    meta = None
            if not year and meta:
                year = meta["year"]
        elif folder_parsed.title and folder_parsed.year:
            title, year = folder_parsed.title, folder_parsed.year
            if self.tmdb.available:
                try:
                    meta = self.tmdb.match(title, year, kind)
                except Exception as ex:
                    plan["skips"].append({"name": folder_raw, "reason": f"TMDB 查询失败: {ex}"})
        else:
            best = max((p for _, p in media), key=score)
            title, year = best.title, best.year
            if self.tmdb.available and title:
                try:
                    meta = self.tmdb.match(title, year, kind)
                except Exception as ex:
                    plan["skips"].append({"name": folder_raw, "reason": f"TMDB 查询失败: {ex}"})
            if meta:
                title = meta["title"] or title
                year = meta["year"] or year
                tmdb_id = meta["id"]
            else:
                tmdb_id = best.tmdb_id

        title = title or folder_raw
        if not tmdb_id and meta:
            tmdb_id = meta.get("id") or ""
        tmdb_id = tmdb_id or folder_parsed.tmdb_id
        original = latin_title((meta or {}).get("original_title") or "")
        # 标题来源（优先级）：手工指定 > TMDB 官方标题 > 目录/文件名解析结果
        if use_tmdb_title and meta and meta.get("title"):
            title = meta["title"]
        if title_override:
            title = title_override

        if not year:
            plan["unmatched"].append({
                "name": group_dir, "guess_title": title, "guess_year": year,
                "reason": "无法确定年份（TMDB 未匹配且目录/文件名无年份）"})
            return

        # 目标目录（三条优先级，均为「少改名」而设）
        #   a. 源目录名本身已合规 → 沿用原名，整体搬走即可
        #   b. 目标库已有同作品目录 → 复用它
        #   c. 都没有 → 按模板新建（此时才加 {tmdbid-N} 标识）
        # canonical_folder=True 时不走 a/b，直接按模板重算（用于纠正明确违规的目录名）
        reuse_source_name = (not canonical_folder) and bool(
            folder_parsed.title and folder_parsed.year and
            folder_parsed.title == title and folder_parsed.year == year)
        if reuse_source_name:
            target_folder = folder_raw
            # 旧式 {tmdb-N} 标识 → 规范 {tmdbid-N}：只改标识格式，一次目录改名
            if normalize_names:
                legacy = LEGACY_TMDB_TAG_RE.search(folder_raw)
                if legacy:
                    v = self.naming.build_vars(title=title, year=year,
                                               tmdb_id=legacy.group(1))
                    canon = self.naming.folder_name(v, kind)
                    if canon and canon != folder_raw:
                        target_folder = canon
        else:
            target_folder = None if canonical_folder else \
                self._find_existing_folder(target_root, title, year)
        if target_folder is None:
            v = self.naming.build_vars(title=title, year=year, tmdb_id=tmdb_id)
            target_folder = self.naming.folder_name(v, kind)
        target_path = f"{target_root.rstrip('/')}/{target_folder}"
        same_folder_name = (target_folder == folder_raw)

        group = {
            "source_dir": group_dir,
            "title": title, "original": original, "year": year,
            "tmdb_id": tmdb_id, "kind": kind, "meta": meta,
            "target_folder": target_folder, "target_path": target_path,
            "files": [],
            # 未归类文件（.txt/压缩包/样本…）：保持原位，因此**禁止**整目录搬移
            "others": [e["name"] for e, _ in others],
        }

        # 集名缓存（tv 单集标题）
        ep_titles: dict[tuple[int, int], str] = {}
        if kind == "tv" and tmdb_id and self.tmdb.available:
            for _, p in media:
                if p.season is not None and p.episode is not None:
                    key = (p.season, p.episode)
                    if key in ep_titles:
                        continue
                    try:
                        ed = self.tmdb.episode_detail(tmdb_id, p.season, p.episode)
                        ep_titles[key] = (ed or {}).get("name") or ""
                    except Exception:
                        ep_titles[key] = ""

        # ── 第一遍：媒体文件目标 ──────────────────────────────
        for e, p in media:
            fname = e["name"]
            cur_dir = e.get("_dir") or group_dir
            item = {"name": fname, "cur_dir": cur_dir, "ext": p.ext,
                    "size": e.get("size") or 0}
            if kind == "movie":
                v = self.naming.build_vars(title=title, original=original, year=year,
                                           tech=p.tech, tmdb_id=tmdb_id)
                new_name = self.naming.movie_file_name(v, p.ext)
                dst_dir = target_path
            else:
                season = p.season or 1
                ep_t = ep_titles.get((p.season or 1, p.episode or 0), "") if p.episode else ""
                v = self.naming.build_vars(title=title, year=year, season=season,
                                           episode=p.episode, tech=p.tech,
                                           tmdb_id=tmdb_id, episode_title=ep_t)
                new_name = self.naming.tv_file_name(v, p.ext)
                # 季目录名：优先沿用文件当前所在的季目录名（Season 1 不改成 Season 01）
                sdir = e.get("_season_dir_name") or self.naming.season_folder_name(season)
                dst_dir = f"{target_path}/{sdir}"
            # 已就位且命名合规 → 不动它（幂等的关键；就位时采用宽容判定）
            if self._same_location(cur_dir, dst_dir, group_dir, target_path) and \
                    self._file_acceptable(p, title, year, kind, lenient=True):
                new_name = fname
            item.update({"new_name": new_name, "dst_dir": dst_dir, "kind": "media"})
            group["files"].append(item)

        # 本组是否会被改动 —— 决定是否「顺带」做 artwork 形态归一
        # （只在本来就要动这个目录时才顺手统一，避免全库无谓重命名）
        needs_work = (not same_folder_name) or any(
            f["new_name"] != f["name"] for f in group["files"] if f.get("kind") == "media")

        # 电影 artwork/nfo 的前缀来源 —— 按「版本」归属，而非全局公共前缀：
        #   单版本（含 DISC1/DISC2 多碟）→ 改后名 stem（多碟取公共前缀）
        #   多版本共存（1080p + 2160p）→ 每个版本各自成套，用 artwork_owner 定位
        media_map = {f["name"]: f for f in group["files"] if f.get("kind") == "media"}
        orig_stems = spec.media_stems(list(media_map))
        new_stems = spec.media_stems([f["new_name"] for f in media_map.values()])
        # 旧 stem → 新 stem（artwork 归属版本后按此跟随改名，绝不错跟）
        new_stem_by_old: dict[str, str] = {}
        for f in media_map.values():
            _o = f["name"].rsplit(".", 1)[0] if "." in f["name"] else f["name"]
            _n = f["new_name"].rsplit(".", 1)[0] if "." in f["new_name"] else f["new_name"]
            new_stem_by_old[_o] = _n
        if not orig_stems:
            default_stem = ""
        elif spec.is_same_version(orig_stems):
            default_stem = spec.common_stem(new_stems)
        else:
            biggest = max(media_map.values(), key=lambda f: f.get("size") or 0)
            default_stem = biggest["new_name"].rsplit(".", 1)[0] \
                if "." in biggest["new_name"] else biggest["new_name"]

        def _stem_for(fname: str) -> str:
            """该伴随文件应跟随的**新**前缀：优先其归属版本，其次代表前缀。"""
            owner = spec.artwork_owner(fname, orig_stems) or spec.nfo_owner(fname, orig_stems)
            if owner and owner in new_stem_by_old:
                return new_stem_by_old[owner]
            return default_stem

        # ── 第二遍：伴随文件（artwork / nfo / 字幕）────────────
        for e, p in companions:
            fname = e["name"]
            cur_dir = e.get("_dir") or group_dir
            item = {"name": fname, "cur_dir": cur_dir, "ext": p.ext}
            dst_default = self._relocate(cur_dir, group_dir, target_path)

            art_kind = spec.parse_artwork(fname) if p.ext in IMAGE_EXTS else ""
            if (normalize_artwork and needs_work and art_kind
                    and self._normalizable_art(fname, kind, cur_dir, group_dir)):
                new_name = spec.normalize_artwork_name(
                    fname, "" if kind == "tv" else _stem_for(fname))
                item.update({"new_name": new_name, "dst_dir": dst_default,
                             "kind": "artwork"})
            elif p.ext == ".nfo" and normalize_artwork and needs_work:
                new_name = spec.nfo_name(kind, "" if kind == "tv" else _stem_for(fname))
                if new_name != fname:
                    item.update({"new_name": new_name, "dst_dir": dst_default,
                                 "kind": "companion"})

            if "new_name" not in item:
                # 跟随「同 stem 前缀的主文件」改名（电影 -poster.jpg 等）
                main_stem = self._find_main_stem(fname, [m[0]["name"] for m in media])
                if main_stem:
                    main_new = next((f["new_name"] for f in group["files"]
                                     if f["name"] == main_stem), "")
                    main_dst = next((f["dst_dir"] for f in group["files"]
                                     if f["name"] == main_stem), target_path)
                    if main_new:
                        stem_new = main_new[:main_new.rfind(".")] if "." in main_new else main_new
                        stem_old = main_stem[:main_stem.rfind(".")] if "." in main_stem else main_stem
                        new_name = fname.replace(stem_old, stem_new, 1)
                        item.update({"new_name": new_name, "dst_dir": main_dst,
                                     "kind": "companion"})
            if "new_name" not in item:
                # 游离同伴文件（海报/nfo/字幕）：保持在原有相对位置，绝不新建季目录
                item.update({"new_name": fname, "dst_dir": dst_default,
                             "kind": "companion-orphan"})
            group["files"].append(item)

        # 该组是否「整目录一次搬走」由 _finalize 统一判定（含「搬走后目录改名」形态）
        group["dir_move_only"] = False

        plan["groups"].append(group)

    @staticmethod
    def _normalizable_art(fname: str, kind: str, cur_dir: str, group_dir: str) -> bool:
        """限定 artwork 归一范围，避免误伤集级图片（S01E01-poster.jpg）。

        剧集：只归一剧集根目录的「无前缀固定名」（poster / fanart / logo / backdrop）
        电影：只归一不含季集号的文件
        """
        from .parser import SEASON_EP_RE
        if SEASON_EP_RE.search(fname):
            return False
        if kind == "tv":
            if cur_dir.rstrip("/") != group_dir.rstrip("/"):
                return False
            stem = fname.rsplit(".", 1)[0].lower()
            return "-" not in stem
        return True

    # ---------- 幂等判定辅助 ----------

    @staticmethod
    def _relocate(cur_dir: str, group_dir: str, target_path: str) -> str:
        """保持文件在组内的相对位置，把父目录换成目标路径。

        group_dir/Season 1/x.nfo → target_path/Season 1/x.nfo
        group_dir/x.nfo          → target_path/x.nfo
        """
        base = group_dir.rstrip("/")
        cur = (cur_dir or base).rstrip("/")
        rel = cur[len(base):].strip("/") if cur.startswith(base) else ""
        return target_path.rstrip("/") + ("/" + rel if rel else "")

    @staticmethod
    def _norm_title(s: str) -> str:
        return re.sub(r"[\s:：\-–—_·！!？?，,。.]+", "", (s or "")).lower()

    def _title_match(self, a: str, b: str) -> bool:
        x, y = self._norm_title(a), self._norm_title(b)
        if not x or not y:
            return False
        return x.startswith(y) or y.startswith(x)

    def _file_acceptable(self, p: ParsedName, title: str, year: str, kind: str,
                         lenient: bool = False) -> bool:
        """文件名是否已达规范（决定「不动它」）。

        lenient=False（默认，用于「不在正确位置」的文件）：要求标题能对上。
        lenient=True（文件已在正确目录里）：只要求年份/集号对得上 —— 存量英文名
        或简化命名一律不折腾，避免全库重命名。

        两种模式都拒绝**规范明确禁止**的结构：文件名带 `{tmdbid-N}` 标识，
        或技术标签包了圆括号（v2.1 起规范为方括号，圆括号属旧工具产物）。
        """
        if violates_filename_spec(p.raw):
            return False
        if kind == "movie":
            if p.year != year:
                return False
            return True if lenient else (bool(p.title) and self._title_match(p.title, title))
        ok = p.season is not None and p.episode is not None
        return ok if lenient else (ok and bool(p.title) and self._title_match(p.title, title))

    def _same_location(self, cur_dir: str, dst_dir: str, group_dir: str, target_path: str) -> bool:
        """文件最终所在目录是否就是它现在的目录（季目录名按季号等价比较）。"""
        cur = cur_dir.rstrip("/")
        dst = dst_dir.rstrip("/")
        if cur == dst:
            return True
        return self._norm_dir(cur.rsplit("/", 1)[-1]) == self._norm_dir(dst.rsplit("/", 1)[-1])

    @staticmethod
    def _norm_dir(name: str) -> str:
        """归一化目录名用于等价比较：Season 1 / Season 01 / S1 → season1。"""
        n = (name or "").strip().lower()
        m = re.match(r"^(?:season|s)\s*0*(\d{1,2})$", n)
        if m:
            return f"season{m.group(1)}"
        return re.sub(r"\s+", "", n)

    def _media_all_ok(self, media: list, title: str, year: str, kind: str) -> bool:
        return bool(media) and all(
            self._file_acceptable(p, title, year, kind, lenient=True) for _, p in media)

    def _find_main_stem(self, companion_name: str, media_names: list[str]) -> str:
        """伴随文件属于哪个主文件：找 stem 前缀匹配最长的。"""
        best = ""
        for mn in media_names:
            stem = mn[:mn.rfind(".")] if "." in mn else mn
            if companion_name.startswith(stem) and len(stem) > len(best):
                best = mn
        return best

    def _find_existing_folder(self, target_root: str, title: str, year: str) -> Optional[str]:
        """在目标库中找已存在的同作品目录（标题+年份一致，容忍无 ID 标识）。

        必须强刷缓存：否则刚建/刚搬的目录读不到，会重复建同名作品目录。
        """
        try:
            entries = self.client.list_all(target_root, refresh=True)
        except Exception:
            return None
        for e in entries:
            if not e.get("is_dir"):
                continue
            name = e.get("name") or ""
            if looks_organized_folder(name, title, year):
                return name
        return None

    def _finalize(self, plan: dict) -> None:
        """把 groups 展开成扁平 actions：mkdir → 目录搬移/文件移动 → 改名 → 清空目录。"""
        actions: list[dict] = []

        # ⓪ 判定每个组能否「整目录一次搬走（可含目录改名）」
        #    条件：① 文件最终位置都在目标目录内且相对子路径不变（剧集 Season 目录不动）；
        #         ② 组内**没有未归类文件**（readme/压缩包等要留在原位，不能被整目录带走）。
        #    这样避免「先 mkdir 出目标目录、再 move_dir 改名」两者**撞名**的老 bug。
        for g in plan["groups"]:
            src_dir = g["source_dir"].rstrip("/")
            dst_dir = g["target_path"].rstrip("/")
            relocatable = bool(g["files"]) and src_dir != dst_dir and not g.get("others")
            if relocatable:
                for f in g["files"]:
                    d = f["dst_dir"].rstrip("/")
                    c = (f.get("cur_dir") or src_dir).rstrip("/")
                    if d == dst_dir:
                        continue
                    if d.startswith(dst_dir + "/") and c.startswith(src_dir + "/") \
                            and d[len(dst_dir):] == c[len(src_dir):]:
                        continue
                    relocatable = False
                    break
            g["_whole_dir_move"] = relocatable
            g["dir_move_only"] = relocatable and not any(
                f["new_name"] != f["name"] for f in g["files"])

        # ① 需要新建的目录（整目录搬移的组不需要；已在原位的目录也不需要）
        existing_dirs = {f.get("cur_dir", "").rstrip("/") for g in plan["groups"] for f in g["files"]}
        existing_dirs |= {g["source_dir"].rstrip("/") for g in plan["groups"]}
        needed_dirs: set[str] = set()
        for g in plan["groups"]:
            if g.get("_whole_dir_move"):
                continue
            for f in g["files"]:
                if f["dst_dir"].rstrip("/") not in existing_dirs:
                    needed_dirs.add(f["dst_dir"])
        for d in sorted(needed_dirs):
            actions.append({"action": "mkdir", "path": d, "status": "pending"})

        # ② 移动
        move_batches: dict[tuple[str, str], list[str]] = {}
        for g in plan["groups"]:
            src_dir = g["source_dir"].rstrip("/")
            dst_dir = g["target_path"].rstrip("/")
            if g.get("_whole_dir_move"):
                # 整目录搬走；目录改名在 move 之后由 rename 动作完成
                for f in g["files"]:
                    f["op"] = "move-with-dir"
                parent = src_dir.rsplit("/", 1)[0]
                name = src_dir.rsplit("/", 1)[1]
                actions.append({"action": "move_dir", "src_parent": parent, "name": name,
                                "dst_parent": dst_dir.rsplit("/", 1)[0],
                                "dst_name": dst_dir.rsplit("/", 1)[1], "status": "pending"})
                continue
            for f in g["files"]:
                cur_dir = (f.get("cur_dir") or src_dir).rstrip("/")
                f_dst = f["dst_dir"].rstrip("/")
                if cur_dir == f_dst and f["name"] == f["new_name"]:
                    f["op"] = "skip-same"
                elif cur_dir == f_dst:
                    f["op"] = "rename-only"
                else:
                    move_batches.setdefault((cur_dir, f_dst), []).append(f["name"])
                    f["op"] = "move"

        for (src, dst), names in sorted(move_batches.items()):
            actions.append({"action": "move", "src_dir": src, "dst_dir": dst,
                            "names": names, "status": "pending"})

        # ③ 改名（只对最终目录里名字需要变的文件）
        for g in plan["groups"]:
            for f in g["files"]:
                if f["new_name"] == f["name"]:
                    continue
                if f.get("op") in ("rename-only", "move", "move-with-dir"):
                    actions.append({"action": "rename",
                                    "path": f"{f['dst_dir'].rstrip('/')}/{f['name']}",
                                    "new_name": f["new_name"], "status": "pending"})

        # ④ 空目录清理（不清理扫描根；只清理「确有文件被搬走」且已搬空的来源目录）
        for g in plan["groups"]:
            src_dir = g["source_dir"].rstrip("/")
            if src_dir == plan["source"].rstrip("/"):
                continue
            if not any(f.get("op") == "move" for f in g["files"]):
                continue  # 没有文件离开该目录 → 不做任何清理
            planned = {f["name"] for f in g["files"]} | {f.get("_dir_name") for f in g["files"]}
            try:
                others = {e["name"] for e in (self.client.list_all(src_dir, refresh=True) or [])}
            except Exception:
                continue  # 目录已不存在 → 无需清理
            if others and planned and others.issubset(planned):
                parent = src_dir.rsplit("/", 1)[0]
                actions.append({"action": "cleanup_empty_dir", "parent": parent,
                                "name": src_dir.rsplit("/", 1)[1], "status": "pending"})

        plan["actions"] = actions
        n_skip = sum(1 for g in plan["groups"] for f in g["files"] if f.get("op") == "skip-same")
        plan["summary"] = {
            "groups": len(plan["groups"]),
            "media_files": sum(1 for g in plan["groups"] for f in g["files"]
                               if f.get("kind") == "media"),
            "dir_moves": sum(1 for a in actions if a["action"] == "move_dir"),
            "moves": sum(1 for a in actions if a["action"] == "move"),
            "renames": sum(1 for a in actions if a["action"] == "rename"),
            "mkdirs": sum(1 for a in actions if a["action"] == "mkdir"),
            "already_ok": n_skip,
            "unmatched": len(plan["unmatched"]),
            "skipped": len(plan["skips"]),
        }
