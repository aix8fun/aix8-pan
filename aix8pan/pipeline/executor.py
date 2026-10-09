"""执行器：按确认后的 Plan 执行（mkdir → move → rename → cleanup）

- 每个动作执行前检查 status，已完成的跳过（断点续跑）
- 全部动作经 OpenList 客户端限速（默认 700ms/操作）
- 必须显式传 confirm=True 才执行（Plan/Execute 分离的安全阀）
"""
from __future__ import annotations

import time

from ..config import load_config
from ..core.openlist import OpenListClient, OpenListError


class Executor:
    def __init__(self, cfg: dict | None = None, client: OpenListClient | None = None):
        self.cfg = cfg or load_config()
        ol = self.cfg["openlist"]
        self.client = client or OpenListClient(
            ol["base_url"], ol["username"], ol["password"], ol["op_interval_ms"])
        self.max_batch = int(self.cfg.get("limits", {}).get("max_execute_batch", 200))

    def execute(self, plan: dict, confirm: bool = False,
                on_progress=None) -> dict:
        """执行 Plan。confirm=False 时只做预检返回动作清单。"""
        actions = plan.get("actions") or []
        if len(actions) > self.max_batch:
            raise RuntimeError(f"动作数 {len(actions)} 超过单次上限 {self.max_batch}，请分批")
        if not confirm:
            return {"precheck": True, "total": len(actions),
                    "message": "dry-run：未执行。传 confirm=True 执行。"}
        if plan.get("status") == "executed":
            return {"precheck": False, "message": "Plan 已执行过", "done": 0, "failed": 0}

        done = failed = 0
        errors: list[str] = []
        for i, act in enumerate(actions):
            if act.get("status") == "done":
                continue
            try:
                self._run_action(act)
                act["status"] = "done"
                done += 1
            except Exception as ex:
                act["status"] = "failed"
                act["error"] = str(ex)[:300]
                failed += 1
                errors.append(f"{act['action']} {act.get('path') or act.get('dst_dir') or act.get('name')}: {act['error']}")
                # 目标目录缺失等结构性失败会连锁报错，直接中断
                if act["action"] == "mkdir":
                    break
            if on_progress:
                on_progress(i + 1, len(actions), act)

        plan["status"] = "executed" if failed == 0 else "partial"
        plan["executed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return {"done": done, "failed": failed, "errors": errors[:20],
                "status": plan["status"]}

    def _run_action(self, act: dict) -> None:
        kind = act["action"]
        if kind == "mkdir":
            # 已存在则跳过
            try:
                self.client.mkdir(act["path"])
            except OpenListError as e:
                if "exist" not in str(e).lower():
                    raise
        elif kind == "move_dir":
            src = f"{act['src_parent'].rstrip('/')}/{act['name']}"
            dst = f"{act['dst_parent'].rstrip('/')}/{act['dst_name']}"
            if src == dst:
                return
            sp = act["src_parent"].rstrip("/")
            dp = act["dst_parent"].rstrip("/")
            name = act["name"]
            if name != act["dst_name"]:
                # **先原地改名，再搬**。反过来（搬完立刻改名）在 115 上不可靠：
                # move 后目标路径尚未进入索引，rename 会报 `object not found`。
                self._rename_with_retry(src, act["dst_name"])
                name = act["dst_name"]
            if sp == dp:
                # 同一父目录 → 就是「原地改名」。
                # **不能**走 move：OpenList/115 会把「源已在目标父目录中」判为冲突，
                # 报 `file [xxx] exists`。
                return
            # 目标已同名目录则先确认（避免覆盖）
            self.client.ensure_dir(act["dst_parent"])
            try:
                self.client.move(sp, [name], dp)
            except OpenListError as e:
                raise RuntimeError(f"目录搬移失败 {name} → {dst}: {e}") from e
        elif kind == "move":
            names = act["names"]
            try:
                self.client.move(act["src_dir"], names, act["dst_dir"])
            except OpenListError:
                # 批量失败降级为逐个移动（学 LitePan）
                moved = []
                for n in names:
                    try:
                        self.client.move(act["src_dir"], [n], act["dst_dir"])
                        moved.append(n)
                    except OpenListError as e2:
                        if "exist" in str(e2).lower() or "same" in str(e2).lower():
                            moved.append(n)
                            continue
                        raise RuntimeError(f"移动 {n} 失败: {e2}") from e2
                act["names"] = [n for n in names if n not in moved]
                if act["names"]:
                    raise RuntimeError(f"移动失败: {act['names']}")
        elif kind == "rename":
            self._rename_with_retry(act["path"], act["new_name"])
        elif kind == "remove":
            # 剧集形态统一：删除集级伴随 / 剧根非标准件（planner 已按 ≤40 分批）
            self._remove_with_retry(act["dir"], act["names"])
        elif kind == "cleanup_empty_dir":
            # 网盘目录状态存在最终一致性，删除前先等一拍再强刷确认真的为空
            time.sleep(1.0)
            items = self.client.list_all(f"{act['parent']}/{act['name']}", refresh=True)
            if not items:
                self.client.remove(act["parent"], [act["name"]])
            # 非空则不动（安全）
        else:
            raise ValueError(f"未知动作: {kind}")

    def _remove_with_retry(self, dir_path: str, names: list[str]) -> None:
        """批量删除 + 失败降级。

        115 对大批量 remove 的响应经常超过 60s 读超时（服务端可能已删/部分删）。
        整批失败 → 逐个重试；「不存在 / not found」视为已删（幂等）。
        """
        try:
            self.client.remove(dir_path, names)
            return
        except OpenListError:
            pass
        failed: list[str] = []
        for n in names:
            try:
                self.client.remove(dir_path, [n])
            except OpenListError as e:
                msg = str(e).lower()
                if "not exist" in msg or "not found" in msg or "exist" in msg:
                    continue  # 已被整批调用删掉
                failed.append(n)
        if failed:
            raise RuntimeError(f"删除失败 {dir_path}: {failed[:5]}")

    def _rename_with_retry(self, path: str, new_name: str, attempts: int = 4) -> None:
        """改名 + 失败重试（每次重试前强制刷新父目录索引）。

        115 网盘目录状态是**最终一致**：任何移动/建目录之后，新路径要过一会儿才进入
        索引，此时 rename 会报「对象不存在」。所以退避重试，并在重试前对父目录做一次
        `refresh=True` 的列表请求把索引刷出来。报「已存在」则视为目标名已就位（幂等）。
        """
        parent = path.rsplit("/", 1)[0] or "/"
        last: Exception | None = None
        for i in range(attempts):
            try:
                self.client.rename(path, new_name)
                return
            except OpenListError as e:
                msg = str(e).lower()
                if "exist" in msg:
                    return
                last = e
                time.sleep(1.0 + i)
                try:
                    self.client.list_all(parent, refresh=True)
                except Exception:
                    pass
        raise last if last else RuntimeError(f"改名失败: {path} → {new_name}")
