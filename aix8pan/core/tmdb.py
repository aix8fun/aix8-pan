"""TMDB 客户端（v3 API，支持镜像 host）

搜索/详情/取图。带请求间隔限速与简单磁盘缓存。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from ..config import CACHE_DIR


class TMDBError(RuntimeError):
    pass


class TMDBClient:
    def __init__(self, api_key: str, api_host: str = "https://tmdb.aws360.cn",
                 image_host: str = "https://tmdb.aws360.cn",
                 language: str = "zh-CN", request_interval_ms: int = 250,
                 cache_dir: Optional[Path] = None, cache_ttl: int = 7 * 24 * 3600):
        self.api_key = api_key
        self.api_host = api_host.rstrip("/")
        self.image_host = image_host.rstrip("/")
        self.language = language
        self.interval = max(0, request_interval_ms) / 1000.0
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_ttl = cache_ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_ts = 0.0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _throttle(self):
        now = time.monotonic()
        wait = self._last_ts + self.interval - now
        if wait > 0:
            time.sleep(wait)
        self._last_ts = time.monotonic()

    def _cache_path(self, kind: str, key: str) -> Path:
        import hashlib
        h = hashlib.md5(f"{kind}:{key}".encode()).hexdigest()[:24]
        return self.cache_dir / f"tmdb_{kind}_{h}.json"

    def _cached(self, kind: str, key: str) -> Optional[dict]:
        p = self._cache_path(kind, key)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            p.unlink(missing_ok=True)   # 损坏的缓存文件顺手清掉
            return None
        if time.time() - d.get("_ts", 0) > self.cache_ttl:
            p.unlink(missing_ok=True)   # 过期即删，缓存目录不无限膨胀
            return None
        return d.get("data")

    def _save_cache(self, kind: str, key: str, data: dict):
        p = self._cache_path(kind, key)
        p.write_text(json.dumps({"_ts": time.time(), "data": data}, ensure_ascii=False),
                     encoding="utf-8")

    def _get(self, path: str, params: dict) -> Any:
        self._throttle()
        params = dict(params)
        params["api_key"] = self.api_key
        url = f"{self.api_host}/3{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            raise TMDBError(f"TMDB HTTP {e.code} {path}: {body}") from e

    # ---------- 公开 API ----------

    def search(self, title: str, year: str = "", media_type: str = "auto") -> dict:
        """搜索。media_type: movie/tv/auto。返回 {movie: [...], tv: [...]}（auto 两种都搜）。"""
        kinds = ["movie", "tv"] if media_type == "auto" else [media_type]
        out: dict[str, list] = {}
        for kind in kinds:
            ck = f"search:{kind}:{title}:{year}:{self.language}"
            cached = self._cached("search", ck)
            if cached is not None:
                out[kind] = cached
                continue
            params = {"query": title, "language": self.language, "page": 1}
            if year and kind == "movie":
                params["year"] = year
            elif year and kind == "tv":
                params["first_air_date_year"] = year
            d = self._get(f"/search/{kind}", params)
            results = (d or {}).get("results") or []
            self._save_cache("search", ck, results)
            out[kind] = results
        return out

    def detail(self, tmdb_id: str, media_type: str) -> dict:
        """详情。movie: /movie/{id}; tv: /tv/{id}（含 seasons 与外部信息）。"""
        ck = f"detail:{media_type}:{tmdb_id}:{self.language}"
        cached = self._cached("detail", ck)
        if cached is not None:
            return cached
        params = {"language": self.language}
        if media_type == "movie":
            params["append_to_response"] = "images"
        else:
            params["append_to_response"] = "images"
        d = self._get(f"/{media_type}/{tmdb_id}", params)
        # 防御：代理对 append_to_response=images 支持不稳定，偶发返回
        # 「images 三组全空」的残缺详情（真实几乎不存在 posters/backdrops/logos
        #  全空的作品）。此时单独拉 /images 合并补齐；仍为空则照常返回但
        #  **不落缓存**，避免坏数据被 cache_ttl（7 天）放大成持续性刮削缺失
        # （2026-10-07 惊天魔盗团3 踩坑：空 images 被缓存导致 clearlogo 刮不到）。
        imgs = d.get("images") if isinstance(d, dict) else None
        if imgs is not None and not (imgs.get("posters") or imgs.get("backdrops")
                                     or imgs.get("logos")):
            try:
                sep = self._get(f"/{media_type}/{tmdb_id}/images", {})
            except Exception:                           # noqa: BLE001
                sep = None
            if isinstance(sep, dict) and (sep.get("posters") or sep.get("backdrops")
                                          or sep.get("logos")):
                d["images"] = {k: sep.get(k) or [] for k in
                               ("posters", "backdrops", "logos")}
                self._save_cache("detail", ck, d)
            # 仍为空：不缓存，下次重试
        else:
            self._save_cache("detail", ck, d)
        return d

    def episode_detail(self, tv_id: str, season: int, episode: int) -> dict:
        ck = f"ep:{tv_id}:{season}:{episode}"
        cached = self._cached("episode", ck)
        if cached is not None:
            return cached
        d = self._get(f"/tv/{tv_id}/season/{season}/episode/{episode}",
                      {"language": self.language})
        self._save_cache("episode", ck, d)
        return d

    def image_url(self, path: str, size: str = "original") -> str:
        return f"{self.image_host}/t/p/{size}{path}"

    def download_image(self, path: str, size: str = "original") -> bytes:
        url = self.image_url(path, size)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    # ---------- 匹配辅助 ----------

    def match(self, title: str, year: str = "", media_type: str = "auto") -> Optional[dict]:
        """智能匹配：优先年份精确匹配，其次第一条结果。

        返回 {id, media_type, title, original_title, year, overview, poster_path, ...}
        """
        if not self.available:
            return None
        res = self.search(title, year, media_type)
        for kind in ("movie", "tv"):
            items = res.get(kind) or []
            if not items:
                continue
            pick = None
            if year:
                for it in items:
                    date = it.get("release_date") or it.get("first_air_date") or ""
                    if date[:4] == year:
                        pick = it
                        break
            if pick is None:
                pick = items[0]
            date = pick.get("release_date") or pick.get("first_air_date") or ""
            return {
                "id": str(pick["id"]),
                "media_type": kind,
                "title": pick.get("title") or pick.get("name") or "",
                "original_title": pick.get("original_title") or pick.get("original_name") or "",
                "year": date[:4],
                "overview": pick.get("overview") or "",
                "poster_path": pick.get("poster_path") or "",
                "backdrop_path": pick.get("backdrop_path") or "",
            }
        return None


def norm_meta(detail: dict, media_type: str) -> dict:
    """把 TMDB 详情规整为刮削用的统一元数据结构。"""
    date = detail.get("release_date") or detail.get("first_air_date") or ""
    images = detail.get("images") or {}
    logos = (images.get("logos") or [])
    logo = next((l for l in logos if l.get("iso_639_1") in (None, "en", "zh")), None)
    seasons = []
    if media_type == "tv":
        for s in detail.get("seasons") or []:
            if s.get("season_number", 0) == 0:
                continue
            seasons.append({
                "season": s.get("season_number"),
                "name": s.get("name") or "",
                "air_date": s.get("air_date") or "",
                "episode_count": s.get("episode_count") or 0,
                "poster_path": s.get("poster_path") or "",
            })
    genres = [g.get("name") for g in detail.get("genres") or [] if g.get("name")]
    return {
        "id": str(detail.get("id") or ""),
        "media_type": media_type,
        "title": detail.get("title") or detail.get("name") or "",
        "original_title": detail.get("original_title") or detail.get("original_name") or "",
        "year": date[:4],
        "overview": detail.get("overview") or "",
        "poster_path": detail.get("poster_path") or "",
        "backdrop_path": detail.get("backdrop_path") or "",
        "logo_path": (logo or {}).get("file_path") or "",
        "rating": detail.get("vote_average") or 0,
        "runtime": detail.get("runtime") or ((detail.get("episode_run_time") or [0])[0] if media_type == "tv" else 0),
        "genres": genres,
        "seasons": seasons,
        "number_of_seasons": detail.get("number_of_seasons") or 0,
    }
