#!/usr/bin/env python3
"""字幕下载与上传（v2.1 命名：{主文件主体}.zh-CN.srt / .en.srt）。

两阶段：
  --download   SubHD 选最佳条目 -> 下载 zip -> 解出 srt -> 转 UTF-8 -> 本地 data/state/subtitles/
  --upload     本地字幕 -> 115 对应作品目录（限速；已存在则跳过）

选片策略（每部两种语言各选一）：
  zh-CN：优先「简体」SRT，无则「双语」SRT 兜底（报告里标记 bilingual_fallback）
  en   ：「英语」SRT
  打分：蓝光/Remux 匹配 +3；分辨率匹配 +2；官方字幕 +2；点赞数 +likes
  多版本目录：同一字幕按各版本主干各命名一份（时间轴同源，差异风险记录在案）

断点续跑：状态 data/state/sub_fetch_state.json。不重复下载已完成的。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.config import state_path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_sub_availability import BASE, UA, fetch, parse_entries, parse_search  # noqa: E402

ROOT = "/115/01-电影"
LOCAL_DIR = state_path("subtitles")
STATE_PATH = state_path("sub_fetch_state.json")
AVAIL_PATH = state_path("sub_avail.json")
SCAN_PATH = state_path("container_scan.json")

SLEEP_SEARCH = 2.0
SLEEP_PAGE = 2.0
SLEEP_PREPARE = 2.2
SLEEP_DOWNLOAD = 1.5
UPLOAD_SLEEP = 1.8

MEDIA_EXTS = {".iso", ".mkv", ".mp4", ".ts", ".avi", ".m2ts", ".wmv", ".flv", ".webm", ".mov"}


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def score_entry(e: dict, lang: str, resolution: str) -> int:
    rel = e["release"].lower()
    s = e.get("likes", 0)
    if "bluray" in rel or "remux" in rel or "blu-ray" in rel:
        s += 3
    if resolution and resolution.lower() in rel:
        s += 2
    if e.get("official"):
        s += 2
    if lang == "zh-CN" and "bilingual" in e["langs"]:
        s -= 1                      # 双语兜底，略降权
    return s


def pick(entries: list[dict], lang: str, resolution: str) -> tuple[dict | None, bool]:
    """返回 (条目, 是否双语兜底)。"""
    pool = [e for e in entries if e["fmt"] == "SRT"]
    if lang == "zh-CN":
        pure = [e for e in pool if "chs" in e["langs"]]
        if pure:
            return max(pure, key=lambda e: score_entry(e, lang, resolution)), False
        bi = [e for e in pool if "bilingual" in e["langs"]]
        if bi:
            return max(bi, key=lambda e: score_entry(e, lang, resolution)), True
        return None, False
    en = [e for e in pool if "en" in e["langs"]]
    if en:
        return max(en, key=lambda e: score_entry(e, lang, resolution)), False
    return None, False


def decode_srt(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_srt(zip_bytes: bytes, lang: str) -> tuple[str | None, bool]:
    """从 zip 中挑出目标语种的 srt 文本。返回 (UTF-8 文本, 是否双语文件)。"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist()
                 if n.lower().endswith((".srt",)) and not n.startswith("__MACOSX")]
        if not names:  # ass 兜底：整包取第一个 ass 转存（保持原格式由调用方决定扩展名）
            names = [n for n in zf.namelist()
                     if n.lower().endswith((".ass", ".ssa")) and not n.startswith("__MACOSX")]
        if not names:
            return None, False
        def lang_rank(n: str) -> tuple[int, int]:
            ln = n.lower()
            bi = 1 if ("&" in ln or "双语" in ln or "bilingual" in ln) else 0
            if lang == "zh-CN":
                for i, k in enumerate(("chs", "zh-cn", ".zh", "简", "cn.")):
                    if k in ln:
                        return (bi, i)          # 同语种命中时纯语种优先于双语
                return (9, 9)
            for i, k in enumerate(("eng", ".en", "英")):
                if k in ln:
                    return (bi, i)
            return (9, 9)
        names.sort(key=lang_rank)
        best = names[0]
        bl = best.lower()
        return decode_srt(zf.read(best)), ("&" in bl or "双语" in bl or "bilingual" in bl)


class RateLimited(Exception):
    """SubHD 下载接口频率限制（403 下载频率过高）。"""


RATE_LIMIT_BACKOFF = 75.0      # 命中限流后的冷却秒数
RATE_LIMIT_RETRIES = 3         # 单条目限流重试次数


def _new_opener() -> urllib.request.OpenerDirector:
    """带 Cookie 会话的 opener（/down/ 校验会话，裸请求 403）。"""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", UA)]
    return opener


def _download_once(sid: str, lang: str) -> tuple[str | None, bool]:
    """完整下载链路跑一次。限流抛 RateLimited，其它失败返回 (None, False)。"""
    opener = _new_opener()
    try:
        opener.open(f"{BASE}/a/{sid}", timeout=20).read()           # 建立会话
        req = urllib.request.Request(
            f"{BASE}/api/sub/prepare-download", data=json.dumps({"sid": sid}).encode(),
            headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            d1 = json.loads(opener.open(req, timeout=20).read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            if e.code == 403 and "频率" in body:
                raise RateLimited(body[:120]) from e
            return None, False
        if not d1.get("success") or not str(d1.get("url", "")).startswith("/down/"):
            return None, False
        time.sleep(SLEEP_DOWNLOAD)
        opener.open(BASE + d1["url"], timeout=20).read()            # 中间页
        req = urllib.request.Request(
            f"{BASE}/api/sub/down", data=json.dumps({"sid": sid}).encode(),
            headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            d2 = json.loads(opener.open(req, timeout=20).read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            if e.code == 403 and "频率" in body:
                raise RateLimited(body[:120]) from e
            return None, False
        if not (d2.get("success") and d2.get("url")):
            return None, False
        time.sleep(0.5)
        blob = opener.open(d2["url"], timeout=30).read()
        if not blob.startswith(b"PK"):
            return None, False
        return extract_srt(blob, lang)
    except RateLimited:
        raise
    except Exception:  # noqa: BLE001
        return None, False


def download_one(sid: str, lang: str) -> tuple[str | None, bool]:
    """条目页 -> prepare -> 中间页 -> api/sub/down -> 真实 zip -> (srt 文本, 是否双语)。

    命中限流时冷却 RATE_LIMIT_BACKOFF 秒并重试，最多 RATE_LIMIT_RETRIES 次。
    """
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        time.sleep(SLEEP_PREPARE)
        try:
            return _download_once(sid, lang)
        except RateLimited:
            if attempt >= RATE_LIMIT_RETRIES:
                return None, False
            print(f"    ⏳ 限流，冷却 {RATE_LIMIT_BACKOFF:.0f}s 后重试…", flush=True)
            time.sleep(RATE_LIMIT_BACKOFF)
    return None, False


def pick_candidates(entries: list[dict], lang: str, resolution: str) -> list[tuple[dict, bool]]:
    """候选条目按「纯语种优先、双语垫底」排序。返回 [(条目, 页面标记即双语)]。"""
    pool = [e for e in entries if e["fmt"] == "SRT"]
    if lang == "zh-CN":
        pure = [e for e in pool if "chs" in e["langs"] and "bilingual" not in e["langs"]]
        bi = [e for e in pool if e not in pure
              and ("chs" in e["langs"] or "bilingual" in e["langs"])]
    else:
        pure = [e for e in pool if "en" in e["langs"]
                and "bilingual" not in e["langs"] and "chs" not in e["langs"]]
        bi = [e for e in pool if e not in pure
              and ("en" in e["langs"] or "bilingual" in e["langs"])]
    return ([(e, False) for e in sorted(pure, key=lambda e: -score_entry(e, lang, resolution))]
            + [(e, True) for e in sorted(bi, key=lambda e: -score_entry(e, lang, resolution))])


def fetch_lang(entries: list[dict], lang: str, resolution: str,
               max_try: int = 4) -> dict:
    """依次尝试候选条目，优先拿到**纯语种**字幕；双语只作兜底。"""
    fallback: dict | None = None
    for entry, page_bi in pick_candidates(entries, lang, resolution)[:max_try]:
        text, zip_bi = download_one(entry["sid"], lang)
        if not text:
            continue
        if not zip_bi:
            return {"status": "ok", "sid": entry["sid"], "release": entry["release"],
                    "bilingual_fallback": page_bi, "text": text}
        if fallback is None:
            fallback = {"status": "ok", "sid": entry["sid"], "release": entry["release"],
                        "bilingual_fallback": True, "text": text}
    if fallback:
        return fallback
    return {"status": "missing"}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"movies": {}}


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def scan_by_tmdb() -> dict[str, dict]:
    """tmdb_id -> 扫描行（path/resolution 等）。"""
    rows = json.loads(SCAN_PATH.read_text(encoding="utf-8"))["rows"]
    return {str(r["tmdb_id"]): r for r in rows}


def cmd_download() -> int:
    avail = {r["tmdb_id"]: r for r in json.loads(AVAIL_PATH.read_text(encoding="utf-8"))["rows"]}
    scan = scan_by_tmdb()
    st = load_state()
    movies = st["movies"]

    def needs_retry(tmdb_id: str) -> bool:
        rec = movies.get(tmdb_id)
        if not rec or rec.get("status") == "error":
            return True
        files = rec.get("files") or {}
        # 有语种没拿到（missing/download_failed）就要重试；真无资源的条目重试也很快
        return any(f.get("status") != "ok" for f in files.values()) or not files

    todo = [t for t in sorted(avail, key=lambda x: int(x)) if needs_retry(t)]
    print(f"作品 {len(avail)}，待下载 {len(todo)}", flush=True)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    for i, tmdb_id in enumerate(todo, 1):
        a = avail[tmdb_id]
        title, year = a["title"], a.get("year") or ""
        res = (scan.get(tmdb_id) or {}).get("resolution") or ""
        prev = movies.get(tmdb_id) or {}
        rec: dict = {"title": title, "year": year, "resolution": res,
                     "files": {l: f for l, f in (prev.get("files") or {}).items()
                               if f.get("status") == "ok"}}   # 保留已成功的语种
        try:
            work_id = a.get("work_id")
            if not work_id:  # 可用性扫描没找到作品页 -> 兜底搜索
                q = urllib.parse.quote(f"{title} {year}".strip())
                html = fetch(f"{BASE}/search/{q}")
                time.sleep(SLEEP_SEARCH)
                ids = parse_search(html)
                if not ids:
                    html = fetch(f"{BASE}/search/{urllib.parse.quote(title)}")
                    time.sleep(SLEEP_SEARCH)
                    ids = parse_search(html)
                if not ids:
                    rec["status"] = "no_work"
                    movies[tmdb_id] = rec
                    save_state(st)
                    print(f"[{i}/{len(todo)}] {title} ({year}) -> no_work", flush=True)
                    continue
                work_id = ids[0]
            rec["work_id"] = work_id
            entries = parse_entries(fetch(f"{BASE}{work_id}"))
            time.sleep(SLEEP_PAGE)
            for lang in ("zh-CN", "en"):
                if lang in rec["files"]:        # 已成功，跳过
                    continue
                got = fetch_lang(entries, lang, res)
                if got["status"] != "ok":
                    rec["files"][lang] = got
                    continue
                safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
                out = LOCAL_DIR / f"{safe_title} ({year}).{lang}.srt"
                out.write_text(got.pop("text"), encoding="utf-8")
                got["local"] = str(out)
                rec["files"][lang] = got
            rec["status"] = "ok"
        except Exception as e:  # noqa: BLE001
            rec["status"] = "error"
            rec["error"] = str(e)[:200]
        movies[tmdb_id] = rec
        save_state(st)
        ok_n = sum(1 for v in rec.get("files", {}).values() if v.get("status") == "ok")
        print(f"[{i}/{len(todo)}] {title} ({year}) -> {rec['status']} (字幕 {ok_n}/2)", flush=True)

    ok = sum(1 for m in movies.values() if m.get("status") == "ok")
    both = sum(1 for m in movies.values()
               if all(m.get("files", {}).get(l, {}).get("status") == "ok" for l in ("zh-CN", "en")))
    print(f"\n下载阶段完成：作品 {ok}/{len(avail)}，双语全齐 {both}", flush=True)
    return 0


def cmd_upload() -> int:
    from aix8pan.core.openlist import OpenListClient
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(
        encoding="utf-8"))["openlist"]
    client = OpenListClient(cfg["base_url"], cfg["username"], cfg["password"],
                            op_interval_ms=cfg.get("op_interval_ms", 400))
    scan = scan_by_tmdb()
    st = load_state()
    movies = st["movies"]
    total = ok = skip = fail = 0
    for tmdb_id, rec in sorted(movies.items(), key=lambda kv: int(kv[0])):
        if rec.get("status") != "ok":
            continue
        row = scan.get(tmdb_id)
        if not row:
            print(f"  ⚠️ {rec.get('title')} 不在扫描表，跳过", flush=True)
            continue
        d = row["path"]
        try:
            entries = client.list_all(d, refresh=True)
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ 列目录失败 {d}: {e}", flush=True)
            continue
        names = {e.get("name") for e in entries}
        stems = sorted({n.rsplit(".", 1)[0] for n in names
                        if n and "." in n and f".{n.rsplit('.', 1)[-1].lower()}" in MEDIA_EXTS})
        if not stems:
            print(f"  ⚠️ {d} 无媒体文件，跳过", flush=True)
            continue
        for lang, f in rec.get("files", {}).items():
            if f.get("status") != "ok" or f.get("uploaded"):
                continue
            text = Path(f["local"]).read_text(encoding="utf-8")
            done_all = True
            for stem in stems:
                total += 1
                remote = f"{d}/{stem}.{lang}.srt"
                if f"{stem}.{lang}.srt" in names:
                    skip += 1
                    continue
                try:
                    client.upload(remote, text.encode("utf-8"))
                    ok += 1
                    time.sleep(UPLOAD_SLEEP)
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    done_all = False
                    print(f"  ❌ {remote}: {e}", flush=True)
                    time.sleep(UPLOAD_SLEEP * 2)
            if done_all:
                f["uploaded"] = True
                save_state(st)
            print(f"  {rec['title']} {lang}: 完成（累计 成功{ok} 跳过{skip} 失败{fail} / 共{total}）",
                  flush=True)
    print(f"\n上传完成：成功 {ok}，跳过 {skip}，失败 {fail}，总 {total}", flush=True)
    return 0 if fail == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    if args.download:
        return cmd_download()
    if args.upload:
        return cmd_upload()
    ap.error("需要 --download 或 --upload")
    return 1


if __name__ == "__main__":
    sys.exit(main())
