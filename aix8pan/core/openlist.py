"""OpenList REST 客户端

封装 OpenList v3 系 API：
- 登录拿 JWT（48h 有效），过期/401 自动重登
- list / mkdir / move / rename / upload(put) / get(直链) / delete
- 所有写操作之间强制间隔（默认 700ms）防 115 风控
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_TIMEOUT = 60
UPLOAD_TIMEOUT = 180


class OpenListError(RuntimeError):
    def __init__(self, message: str, code: int = 0):
        super().__init__(f"[{code}] {message}")
        self.code = code


class OpenListClient:
    def __init__(self, base_url: str, username: str, password: str,
                 op_interval_ms: int = 700, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.op_interval = max(0, op_interval_ms) / 1000.0
        self.timeout = timeout
        self._token: Optional[str] = None
        self._last_op_ts = 0.0

    # ---------- 内部 ----------

    def _throttle(self) -> None:
        """写操作限速：两次操作之间至少间隔 op_interval 秒。"""
        now = time.monotonic()
        wait = self._last_op_ts + self.op_interval - now
        if wait > 0:
            time.sleep(wait)
        self._last_op_ts = time.monotonic()

    def _login(self) -> None:
        body = json.dumps({"username": self.username, "password": self.password}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/auth/login", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            d = json.loads(resp.read().decode())
        if d.get("code") != 200:
            raise OpenListError(f"登录失败: {d.get('message')}", d.get("code", 0))
        self._token = d["data"]["token"]

    def _request(self, method: str, api: str, payload: Optional[dict] = None,
                 raw_body: Optional[bytes] = None, extra_headers: Optional[dict] = None,
                 timeout: Optional[int] = None, retry_on_401: bool = True,
                 throttle: bool = True) -> Any:
        if throttle:
            self._throttle()
        if self._token is None:
            self._login()
        headers = {"Authorization": self._token or "", "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        data = raw_body if raw_body is not None else (
            json.dumps(payload).encode() if payload is not None else None)
        req = urllib.request.Request(
            f"{self.base_url}{api}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry_on_401:
                self._token = None
                self._login()
                return self._request(method, api, payload, raw_body, extra_headers,
                                     timeout, retry_on_401=False, throttle=False)
            body = e.read().decode(errors="replace") if e.fp else ""
            raise OpenListError(f"HTTP {e.code} {api}: {body[:300]}", e.code) from e
        if not text:
            return {}
        d = json.loads(text)
        if d.get("code") != 200:
            raise OpenListError(f"{api}: {d.get('message')}", d.get("code", 0))
        return d.get("data")

    # ---------- 读操作 ----------

    def list_dir(self, path: str, page: int = 1, per_page: int = 1000,
                 refresh: bool = False) -> list[dict]:
        """列目录。返回条目列表（name/is_dir/size/modified）。"""
        data = self._request("POST", "/api/fs/list", {
            "path": path, "page": page, "per_page": per_page,
            "refresh": refresh, "password": "",
        }, throttle=False)
        return (data or {}).get("content") or []

    def list_all(self, path: str, refresh: bool = False) -> list[dict]:
        """翻页拉取目录下全部条目。"""
        items: list[dict] = []
        page = 1
        while True:
            batch = self.list_dir(path, page=page, per_page=1000, refresh=refresh and page == 1)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 1000:
                break
            page += 1
        return items

    def get_info(self, path: str) -> dict:
        return self._request("POST", "/api/fs/get", {"path": path}, throttle=False) or {}

    def get_download_url(self, path: str) -> str:
        """取下载直链（供 ffprobe / 封面提取用）。"""
        info = self.get_info(path)
        url = info.get("raw_url") or ""
        if not url:
            raise OpenListError(f"未取到直链: {path}")
        return url

    def search(self, parent: str, keywords: str, scope: int = 0) -> list[dict]:
        """在 parent 下搜索（scope: 0=仅当前目录所有子层）。"""
        data = self._request("POST", "/api/fs/search", {
            "parent": parent, "keywords": keywords,
            "page": 1, "per_page": 100, "scope": scope,
        }, throttle=False)
        return (data or {}).get("content") or []

    # ---------- 写操作（全部限速） ----------

    def mkdir(self, path: str) -> None:
        self._request("POST", "/api/fs/mkdir", {"path": path})

    def rename(self, path: str, new_name: str) -> None:
        """重命名（同目录内改名）。

        ⚠️ 实测（2026-10-07 沙盒）OpenList 的 115 驱动**不按全名重命名**：它只取
        `new_name` 的基名（去掉最后一段扩展名），再拼上**源文件原有的扩展名**。
        例：`p.txt` → rename 到 `hello.nfo`，实际得到的是 `hello.txt`。
        因此跨扩展名改名在本平台上无法实现 —— 必须拦住，否则会静默产生错名文件
        （若无脑改回，就会得到 `x.nfo.nfo` 这种名字）。
        """
        if os.path.splitext(new_name)[1] != os.path.splitext(path)[1]:
            raise OpenListError(
                f"115 平台不支持跨扩展名改名（驱动会保留源扩展名）: "
                f"{path} → {new_name}；请改用「删除 + 重新上传」")
        self._request("POST", "/api/fs/rename", {"path": path, "name": new_name})

    def move(self, src_dir: str, names: list[str], dst_dir: str) -> None:
        # 批量搬移大目录（数百集）时 OpenList 端处理可达数分钟，
        # 默认 60s 读超时会被误判失败（实际服务端仍在执行），放宽到 600s。
        self._request("POST", "/api/fs/move", {
            "src_dir": src_dir, "dst_dir": dst_dir, "names": names},
            timeout=600)

    def copy(self, src_dir: str, names: list[str], dst_dir: str) -> None:
        self._request("POST", "/api/fs/copy", {
            "src_dir": src_dir, "dst_dir": dst_dir, "names": names})

    def remove(self, dir_path: str, names: list[str]) -> None:
        self._request("POST", "/api/fs/remove", {"dir": dir_path, "names": names})

    def upload(self, remote_path: str, content: bytes, overwrite: bool = False) -> None:
        """上传字节内容到远端完整路径 remote_path。

        overwrite=False（默认）：路径已存在时**不覆盖**（115 的 PUT 对已存在文件
        会返回成功但内容不变，属于静默无操作，必须靠调用方先判断）。
        overwrite=True：先删后传 —— 这是 115 上唯一可靠的「覆盖」方式。

        ⚠️ 实测（2026-10-07 沙盒复现）：115 **允许同目录下存在多个同名文件**。
        对已存在路径直接 PUT 不会覆盖，而是**再建一个同名条目**；而 `/api/fs/list`
        会把同名条目折叠成一条（只显示其中一个），所以这种重复在接口侧几乎不可见
        —— 只有 115 网页端能看到两条。因此「先删后传」里的删除必须**回读确认**，
        删不干净时宁可报错也不能继续传。
        """
        if overwrite:
            parent, _, name = remote_path.rpartition("/")
            parent = parent or "/"
            for _ in range(3):
                try:
                    self.remove(parent, [name])
                except OpenListError:
                    pass                  # 不存在则忽略
                time.sleep(0.4)           # 等 115 最终一致
                if not any((e.get("name") or "") == name
                           for e in self.list_all(parent, refresh=True)):
                    break
            else:
                raise OpenListError(
                    f"同名条目未能清除，已放弃上传以免产生重复文件: {remote_path}")
        quoted = urllib.parse.quote(remote_path, safe="/")
        self._request("PUT", "/api/fs/put", raw_body=content,
                      extra_headers={
                          "File-Path": quoted,
                          "Content-Type": "application/octet-stream",
                          "Content-Length": str(len(content)),
                      }, timeout=UPLOAD_TIMEOUT)

    def upload_file(self, remote_path: str, local_path: str, overwrite: bool = False) -> None:
        from pathlib import Path
        content = Path(local_path).read_bytes()
        self.upload(remote_path, content, overwrite=overwrite)

    # ---------- 便捷方法 ----------

    def ensure_dir(self, path: str) -> None:
        """逐级确保目录存在（存在则跳过，静默处理已存在错误）。"""
        parts = [p for p in path.split("/") if p]
        cur = ""
        for part in parts:
            cur += "/" + part
            try:
                self.mkdir(cur)
            except OpenListError as e:
                if "exist" not in str(e).lower() and "already" not in str(e).lower():
                    # 试着列一下确认存在
                    try:
                        items = self.list_dir("/", per_page=1, refresh=False)
                        _ = items
                    except Exception:
                        raise e

    def exists(self, path: str) -> bool:
        try:
            self.get_info(path)
            return True
        except OpenListError:
            return False
