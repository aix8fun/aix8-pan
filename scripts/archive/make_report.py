#!/usr/bin/env python
"""把 data/state/container_scan.json 渲染成 xlsx 核对表（**只读**，不碰网盘）。

输出: ~/WorkBuddy/aix8-pan/合集_专辑_作品规范核对表.xlsx
  Sheet1 作品清单   —— 逐作品一行，含「是否符合规范」
  Sheet2 问题清单   —— 逐问题一行（可整改项）
  Sheet3 规范速查   —— 现行命名规范摘要
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aix8pan.config import state_path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

SRC = state_path("container_scan.json")
TVF = state_path("title_verify.json")
LKF = state_path("115_cids.json")          # tests/fetch_115_cids.py 产出
OUT = Path.home() / "WorkBuddy/aix8-pan/合集_专辑_作品规范核对表.xlsx"

# ── 样式 ────────────────────────────────────────────────────
C_HEAD = "1F3864"        # 表头深蓝
C_HEAD_TXT = "FFFFFF"
C_OK = "E2EFDA"          # 合规 浅绿
C_OK_TXT = "375623"
C_BAD = "FCE4E4"         # 不合规 浅红
C_BAD_TXT = "9C0006"
C_MID = "FFF2CC"         # 仅提示 浅黄
C_MID_TXT = "7F6000"
C_ALT = "F7F9FC"         # 隔行
C_GRP = "D9E1F2"         # 系列分组底色

THIN = Side(style="thin", color="D0D7E5")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(vertical="center", wrap_text=True)
CENTER = Alignment(horizontal="center", vertical="center")


def style_header(ws, ncol: int, row: int = 1, height: int = 30, freeze_col: int = 5):
    ws.row_dimensions[row].height = height
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = PatternFill("solid", fgColor=C_HEAD)
        cell.font = Font(bold=True, color=C_HEAD_TXT, size=10.5)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    # 用字符串地址设置冻结，避免 ws.cell() 触发 write-only 边界扩张产生空行
    ws.freeze_panes = f"{get_column_letter(freeze_col)}{row + 1}"


def verdict(r: dict) -> tuple[str, str, str]:
    """返回 (结论文本, 填充色, 字色)。"""
    if r["conform"]:
        return "✅ 符合", C_OK, C_OK_TXT
    if r["n_err"] == 0:
        return "⚠️ 基本符合", C_MID, C_MID_TXT
    return "❌ 不符合", C_BAD, C_BAD_TXT


def join_issues(r: dict) -> str:
    parts = []
    for e in r["errors"]:
        parts.append("【必须整改】" + e)
    for w in r["warns"]:
        parts.append("【建议整改】" + w)
    for i in r["infos"]:
        parts.append("【提示】" + i)
    return "\n".join(parts)


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows = data["rows"]
    # TMDB 标题核对结果（若已跑 verify_titles.py）
    tv: dict[tuple, dict] = {}
    if TVF.exists():
        for r in json.loads(TVF.read_text(encoding="utf-8")):
            tv[(r["container"], r["folder"])] = r
    # 115 目录深链（若已跑 fetch_115_cids.py）
    links: dict[str, str] = {}
    if LKF.exists():
        links = {k: v["url"] for k, v in
                 json.loads(LKF.read_text(encoding="utf-8"))["map"].items()}
    wb = Workbook()

    # ══════════ Sheet1 作品清单 ══════════
    ws = wb.active
    ws.title = "作品清单"
    heads = [
        "序号", "分类", "所在系列", "原文件名（作品目录）", "目录链接", "作品名", "年份",
        "TMDB ID", "TMDB 官方中文名", "ID 标识", "体积(MB)", "媒体文件数", "文件总数",
        "版本数", "主文件名", "分辨率", "技术规格", "海报/图片文件", "目录命名", "文件命名",
        "海报/NFO", "是否符合规范", "问题说明", "规范目录名（应为）",
    ]
    COL = {name: i for i, name in enumerate(heads, 1)}   # 列名 → 列号，避免硬编码下标
    ws.append(heads)
    style_header(ws, len(heads), freeze_col=COL["目录链接"] - 1)

    for i, r in enumerate(rows, 1):
        vt, fill, txt = verdict(r)
        rec = tv.get((r["container"], r["folder_raw"])) or {}
        tmdb_title = rec.get("tmdb_title", "") or "—"
        if rec.get("issues") and "TITLE_MISMATCH" in rec["issues"]:
            tmdb_title += "  ← 标题不一致"
        elif rec.get("issues") and "EXTRA_SEGMENT" in rec["issues"]:
            tmdb_title += "  ← 多出修饰词"
        elif rec.get("issues") and "NO_CJK_TITLE" in rec["issues"]:
            tmdb_title += "  ← TMDB 无中文名"
        url = links.get(r["path"], "")
        ws.append([
            i, r["category"], r["container"], r["folder_raw"], url or "—",
            r["title"], r["year"],
            r["tmdb_id"], tmdb_title, r["id_tag_raw"] or "—", r["size_mb"],
            r["media_count"], r.get("files_total", "—"), r["version_count"],
            r["main_file"], r["resolution"] or "—",
            r["tech_all"] or "—",
            "\n".join(r["images"]) if r["images"] else "—",
            "✅" if r["folder_ok"] else "❌",
            "✅" if r["file_ok"] else "❌",
            "✅" if r["art_ok"] else "❌",
            vt, join_issues(r) or "—", r["expected_folder"],
        ])
        n = ws.max_row
        for c in range(1, len(heads) + 1):
            cell = ws.cell(row=n, column=c)
            cell.border = BORDER
            cell.alignment = WRAP
            cell.font = Font(size=10)
        # 目录链接：蓝色下划线 + 超链接
        lc = ws.cell(row=n, column=COL["目录链接"])
        if url:
            lc.hyperlink = url
            lc.font = Font(size=10, color="0563C1", underline="single")
        # 综合结论列着色
        vc = ws.cell(row=n, column=COL["是否符合规范"])
        vc.fill = PatternFill("solid", fgColor=fill)
        vc.font = Font(size=10, bold=True, color=txt)
        vc.alignment = CENTER
        # 标题核对差异标色
        if "←" in str(tmdb_title):
            ws.cell(row=n, column=COL["TMDB 官方中文名"]).font = Font(size=10, color="C00000")
        # 三个分项列着色
        for name in ("目录命名", "文件命名", "海报/NFO"):
            cc = ws.cell(row=n, column=COL[name])
            cc.alignment = CENTER
            cc.font = Font(size=11, color=C_OK_TXT if cc.value == "✅" else C_BAD_TXT)
        for name in ("序号", "分类", "年份", "TMDB ID", "体积(MB)", "媒体文件数",
                     "文件总数", "版本数", "分辨率"):
            ws.cell(row=n, column=COL[name]).alignment = CENTER
        # 年份/ID 以文本呈现，避免被当数字
        ws.cell(row=n, column=COL["年份"]).number_format = "@"
        ws.cell(row=n, column=COL["TMDB ID"]).number_format = "@"

    widths = [5, 7, 26, 34, 46, 18, 7, 10, 26, 14, 10, 9, 9, 7, 46, 11, 30, 34, 8, 8, 9, 13, 46, 34]
    for idx, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    ws.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{ws.max_row}"

    # ══════════ Sheet2 问题清单 ══════════
    ws2 = wb.create_sheet("问题清单")
    h2 = ["序号", "级别", "问题码", "分类", "所在系列", "作品目录", "问题说明", "整改建议"]
    ws2.append(h2)
    style_header(ws2, len(h2), height=26)

    LV = {"error": ("必须整改", C_BAD, C_BAD_TXT),
          "warn": ("建议整改", C_MID, C_MID_TXT),
          "info": ("提示", C_ALT, "404040")}
    k = 0
    for r in rows:
        if r["conform"] and not r["infos"]:
            continue
        for item in r.get("issues", []):
            k += 1
            lab, fill, txt = LV[item["level"]]
            ws2.append([k, lab, item["code"], r["category"], r["container"],
                        r["folder_raw"], item["detail"], item["suggestion"]])
            n = ws2.max_row
            for c in range(1, len(h2) + 1):
                cc = ws2.cell(row=n, column=c)
                cc.border = BORDER
                cc.alignment = WRAP
                cc.font = Font(size=10)
            ws2.cell(row=n, column=2).fill = PatternFill("solid", fgColor=fill)
            ws2.cell(row=n, column=2).font = Font(size=10, bold=True, color=txt)
            ws2.cell(row=n, column=2).alignment = CENTER
            ws2.cell(row=n, column=3).alignment = CENTER
    for idx, w in enumerate([5, 10, 20, 7, 26, 34, 60, 46], 1):
        ws2.column_dimensions[get_column_letter(idx)].width = w
    ws2.auto_filter.ref = f"A1:{get_column_letter(len(h2))}{ws2.max_row}"

    wb.save(OUT)
    print(f"saved {OUT}")
    print(f"作品 {len(rows)} 行；问题 {k} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
