#!/usr/bin/env python
"""把工作区路径映射成 115 的目录 ID（cid），产出可点击的 115 深链。

为什么要读浏览器 Cookie
────────────────────────────────────────────────────────────
115 的网页深链是 `https://115.com/?cid=<cid>&offset=0&mode=wangpan`，
而 **cid 无法从 OpenList 拿到**（`/api/fs/list`、`/api/fs/get` 都不返回 id）。
唯一可靠来源是 115 官方接口 —— 需要你自己的登录态。

⚠️ 注意：115 的 UID / CID / SEID / KID 都是**会话型 cookie**，
Chrome 只把它们留在内存里，复制 profile 目录也带不过去（新实例一定是未登录），
所以只能**就地解密本机 Chrome 的 Cookie 数据库**（只读，密钥取自 macOS 钥匙串）。

用法：
    <venv>/python scripts/fetch_115_cids.py            # 只读扫描 → data/state/115_cids.json
    <venv>/python scripts/fetch_115_cids.py --profile "Profile 1"
    <venv>/python scripts/fetch_115_cids.py --incremental
        增量模式：复用 data/state/115_cids.json 缓存（cid 与目录绑定，改名/移动不变），
        只为缓存里没有的目标路径下钻解析；缓存中已不存在的路径自动剔除。

只做两件事：① 列出「目标目录的祖先链」；② 记录每个目录的 cid。
不会对网盘做任何写操作。Cookie 值只在内存里用，不落盘、不打印。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aix8pan.paths import state_path

SCAN = state_path("container_scan.json")
OUT = state_path("115_cids.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
API = "https://webapi.115.com/files"
ROOT_CID = "0"
SLEEP = 0.5          # 115 有频控，逐层下钻时保持克制；清单本身不大（~65 次）
CONTAINER_MIN_DEPTH = 2   # 从「合集」「专辑」这一层开始输出容器目录


# ── 1. 取本机 Chrome 的 115 登录态 ────────────────────────────────

def chrome_cookie_jar(profile: str = "Default") -> dict[str, str]:
    """解密本机 Chrome Cookie 库里的 115 cookie（只读）。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    db = (Path.home() / "Library/Application Support/Google/Chrome" /
          profile / "Cookies")
    if not db.exists():
        raise SystemExit(f"未找到 Chrome Cookie 库: {db}")

    pw = subprocess.run(
        ["security", "find-generic-password", "-w",
         "-s", "Chrome Safe Storage", "-a", "Chrome"],
        capture_output=True, text=True).stdout.strip()
    if not pw:
        raise SystemExit("无法从钥匙串读取 Chrome Safe Storage 密钥")
    key = hashlib.pbkdf2_hmac("sha1", pw.encode(), b"saltysalt", 1003, 16)

    def dec(blob: bytes) -> str:
        if blob[:3] in (b"v10", b"v11"):
            blob = blob[3:]
        d = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        out = d.update(blob) + d.finalize()
        if out and 1 <= out[-1] <= 16:
            out = out[:-out[-1]]
        if len(out) > 32 and not all(32 <= b < 127 for b in out[:32]):
            out = out[32:]                      # 旧格式的域名哈希前缀
        return out.decode("utf-8", "replace")

    jar: dict[str, str] = {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    for name, val, enc in con.execute(
            "select name, value, encrypted_value from cookies "
            "where host_key like '%115.com'"):
        if name in jar:
            continue
        try:
            jar[name] = dec(enc) if enc else (val or "")
        except Exception:
            pass
    missing = [k for k in ("UID", "CID", "SEID") if not jar.get(k)]
    if missing:
        raise SystemExit(f"缺少关键 cookie {missing}：请确认 Chrome 里已登录 115")
    return jar


# ── 2. 调 115 接口 ───────────────────────────────────────────────

class C115:
    def __init__(self, jar: dict[str, str]):
        self.cookie = "; ".join(f"{k}={v}" for k, v in jar.items() if v)

    def ls(self, cid: str) -> list[dict]:
        q = urllib.parse.urlencode({
            "aid": 1, "cid": cid, "o": "user_ptime", "asc": 0,
            "offset": 0, "show_dir": 1, "limit": 1000, "snap": 0,
            "natsort": 1, "format": "json",
        })
        req = urllib.request.Request(f"{API}?{q}", headers={
            "Cookie": self.cookie, "User-Agent": UA,
            "Referer": "https://115.com/", "Origin": "https://115.com",
            "Accept": "application/json, text/plain, */*"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        if not d.get("state"):
            raise SystemExit(f"115 接口返回异常: {json.dumps(d, ensure_ascii=False)[:200]}")
        return d.get("data") or []


# ── 3. 只沿「需要的祖先链」下钻 ───────────────────────────────────

def main() -> int:
    argv = sys.argv[1:]
    profile = "Default"
    incremental = "--incremental" in argv
    if "--profile" in argv:
        profile = argv[argv.index("--profile") + 1]

    data = json.loads(SCAN.read_text(encoding="utf-8"))
    # 工作区路径 /115/01-电影/合集/… → 去掉挂载前缀，变成 115 里的相对层级
    targets: list[tuple[str, ...]] = []
    for r in data["rows"]:
        segs = tuple(p for p in r["path"].split("/") if p)
        if segs and segs[0] == "115":
            segs = segs[1:]
        targets.append(segs)
        # 容器目录（合集/专辑、系列目录、漫威宇宙中间层）也一并输出，
        # 报表要用它们生成 collection_pan_link。这些 cid 本来就是解析
        # 过程中的中间产物，只是原先没写进结果，故**不额外增加请求**。
        for k in range(CONTAINER_MIN_DEPTH, len(segs)):
            targets.append(segs[:k])
    seen: set[tuple[str, ...]] = set()
    targets = [t for t in targets if not (t in seen or seen.add(t))]
    print(f"目标目录 {len(targets)} 个（含容器目录）")

    # 增量：读缓存，只为缺失路径下钻
    old_map: dict[str, str] = {}
    if incremental and OUT.exists():
        old_map = {p: v["cid"] for p, v in
                   json.loads(OUT.read_text(encoding="utf-8"))["map"].items()}

    def key(t: tuple[str, ...]) -> str:
        return "/115/" + "/".join(t)

    missing = [t for t in targets if key(t) not in old_map] if incremental else targets
    if incremental:
        print(f"增量模式：缓存命中 {len(targets) - len(missing)} 个，待解析 {len(missing)} 个")

    # 需要列出的目录 = 每个待解析目标的全部祖先（目标自身不必列出）
    need: set[tuple[str, ...]] = set()
    for t in missing:
        for k in range(len(t)):
            need.add(t[:k])

    # 每个目录要在父层里认领哪些子项（祖先 + 目标本身）
    want: dict[tuple[str, ...], set[str]] = {}
    for t in set(need) | set(missing):
        for k in range(1, len(t) + 1):
            want.setdefault(t[:k - 1], set()).add(t[k - 1])

    cids: dict[tuple[str, ...], str] = {(): ROOT_CID}
    if incremental:
        # 用缓存 cid 作种子：已知的祖先/兄弟目录直接跳过，不再请求
        for p, cid in old_map.items():
            segs = tuple(x for x in p.split("/") if x)
            if segs and segs[0] == "115":
                segs = segs[1:]
            cids[segs] = cid
        # 已被种子覆盖的认领项无需再列父目录
        for t in list(missing):
            for k in range(1, len(t) + 1):
                if t[:k] in cids and t[:k - 1] in want:
                    want[t[:k - 1]].discard(t[k - 1])

    c = C115(chrome_cookie_jar(profile))
    unresolved: list[str] = []
    n_ls = 0

    if need:
        for depth in range(0, max(len(x) for x in need) + 1):
            for p in sorted(x for x in need if len(x) == depth):
                names = want.get(p, set())
                if p not in cids:
                    if names:
                        unresolved.append("/".join(p) or "<root>")
                    continue
                names = {n for n in names if p + (n,) not in cids}
                if not names:
                    continue
                kids = c.ls(cids[p])
                n_ls += 1
                index = {k.get("n"): str(k.get("cid")) for k in kids
                         if str(k.get("cid")) not in ("", "0")}
                for name in names:
                    if name in index:
                        cids[p + (name,)] = index[name]
                    else:
                        unresolved.append("/".join(p + (name,)))
                print(f"  L{depth} {('/'.join(p) or '<root>'):<44} "
                      f"子项 {len(index)}／需认领 {len(names)}")
                time.sleep(SLEEP)

    out: dict[str, dict] = {}
    for t in targets:
        cid = cids.get(t)
        if not cid:
            unresolved.append("/".join(t))
            continue
        out[key(t)] = {
            "cid": cid,
            "url": f"https://115.com/?cid={cid}&offset=0&mode=wangpan",
        }
    if incremental:
        print(f"  实际请求 115 接口 {n_ls} 次")

    OUT.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(out), "mount_prefix": "/115",
        "map": out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}  解析成功 {len(out)}/{len(targets)}")
    if unresolved:
        print(f"⚠ 未解析 {len(unresolved)} 个：")
        for u in unresolved[:20]:
            print("   ", u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
