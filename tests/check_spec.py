"""规范冻结守门校验（check_spec）

规则一旦冻结就不该悄悄漂移。本脚本对**已冻结的电影命名规范 v2.0** 做三重校验：

  A. 行为契约 —— 用固定黄金样例跑真实代码路径，逐一比对期望输出
  B. 文档一致 —— SPEC.md / SKILL.md / README.md 的关键条目与事实源一致
  C. 配置一致 —— config.json 的 naming 模板不得偏离 naming_spec

任何一项失败 = 「冻结规则被改动」，退出码非 0。

改规则时的正确顺序（SPEC.md §0）：
  1. 改 aix8pan/naming_spec.py（唯一事实源）
  2. 同步 SPEC.md / SKILL.md 速查
  3. 跑本脚本 + tests/test_parser_naming.py（必须全绿）
  4. 跑 scripts/run_audit.py /115/01-电影 确认存量仍全合规（幂等）

用法：
    python3 tests/check_spec.py          # 只校验规则本身
    python3 tests/check_spec.py --quiet  # 只输出失败项与汇总
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aix8pan import naming_spec as spec                      # noqa: E402
from aix8pan.naming import NamingEngine, sanitize            # noqa: E402
from aix8pan.parser import parse_media_name                  # noqa: E402

SPEC_MD = ROOT / "SPEC.md"
README_MD = ROOT / "README.md"
SKILL_MD = Path.home() / ".workbuddy" / "skills" / "pan115-butler" / "SKILL.md"
CONFIG_JSON = ROOT / "config.json"

# 存量样板（黄金样例的锚点，与 SPEC.md / 单测同一份真实字节）
STEM = "大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos]"

_RESULTS: list[tuple[bool, str, str, object, object]] = []


def check(group: str, name: str, got, want) -> None:
    _RESULTS.append((got == want, group, name, got, want))


def doc_has(group: str, path: Path, token: str) -> None:
    if not path.exists():
        _RESULTS.append((False, group, f"{path.name} 存在", "文件缺失", "存在"))
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    _RESULTS.append((token in text, group, f"{path.name} 含 {token!r}", token in text, True))


# ═══════════════ A. 行为契约（电影规则黄金样例）═══════════════

def check_frozen_metadata() -> None:
    g = "A0 冻结元数据"
    check(g, "SCOPE_STATUS[movie] == frozen", spec.SCOPE_STATUS.get("movie"), "frozen")
    check(g, "SPEC_VERSION 已定义", bool(spec.SPEC_VERSION), True)
    want_keys = {
        "folder_template", "file_template", "artwork_style", "artwork_keywords",
        "nfo_style", "tech_order", "tech_sep", "colon", "multi_version", "id_placement",
    }
    check(g, "FROZEN_MOVIE_RULES 条目齐全",
          want_keys <= set(spec.FROZEN_MOVIE_RULES), True)
    # 表里的模板必须就是代码里的模板（不可能漂移，但表被删/被改要能发现）
    check(g, "冻结表 folder_template == 常量",
          spec.FROZEN_MOVIE_RULES["folder_template"], spec.MOVIE_FOLDER_TEMPLATE)
    check(g, "冻结表 file_template == 常量",
          spec.FROZEN_MOVIE_RULES["file_template"], spec.MOVIE_FILE_TEMPLATE)


def check_folder_and_file() -> None:
    g = "A1 目录 / 文件名"
    n = NamingEngine({})          # 空配置 → 全部回落 naming_spec（验证兜底链）
    v = n.build_vars(title="大黄蜂", year="2018", tmdb_id="424783")
    check(g, "电影目录", n.folder_name(v, "movie"), "大黄蜂 (2018) {tmdbid-424783}")
    check(g, "剧集目录带 ID（v2.2）", n.folder_name(v, "tv"), "大黄蜂 (2018) {tmdbid-424783}")
    check(g, "电影目录无 ID 时不留空括号",
          n.folder_name(n.build_vars(title="大黄蜂", year="2018"), "movie"), "大黄蜂 (2018)")
    check(g, "季目录两位补零", n.season_folder_name(1), "Season 01")

    fv = n.build_vars(title="大黄蜂", original="Bumblebee", year="2018",
                      tech="2160p TrueHD Atmos")
    check(g, "电影文件名", n.movie_file_name(fv, ".iso"),
          "大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso")
    check(g, "英文原名为空时不留双空格",
          n.movie_file_name(n.build_vars(title="大黄蜂", year="2018",
                                         tech="2160p TrueHD Atmos"), ".iso"),
          "大黄蜂 (2018) [2160p TrueHD Atmos].iso")


def check_artwork_and_nfo() -> None:
    g = "A2 artwork / nfo"
    check(g, "电影海报前缀式", spec.artwork_name("poster", STEM), STEM + "-poster.jpg")
    check(g, "电影背景图前缀式", spec.artwork_name("fanart", STEM), STEM + "-fanart.jpg")
    check(g, "电影 logo（clearlogo）", spec.artwork_name("clearlogo", STEM), STEM + "-clearlogo.png")
    check(g, "logo → clearlogo 归一", spec.artwork_name("logo", STEM), STEM + "-clearlogo.png")
    check(g, "backdrop → fanart 归一", spec.artwork_name("backdrop", STEM), STEM + "-fanart.jpg")
    check(g, "剧集海报无前缀", spec.artwork_name("poster"), "poster.jpg")
    check(g, "电影 nfo 与主文件同名", spec.nfo_name("movie", STEM), STEM + ".nfo")
    check(g, "剧集 nfo 固定名", spec.nfo_name("tv"), "tvshow.nfo")
    check(g, "季海报命名", spec.season_poster_name(1), "season01-poster.jpg")

    check(g, "识别前缀式 poster", spec.parse_artwork("xxx-poster.jpg"), "poster")
    check(g, "识别旧 logo", spec.parse_artwork("logo.png"), "clearlogo")
    check(g, "识别旧 backdrop", spec.parse_artwork("backdrop.jpg"), "fanart")
    check(g, "季海报识别", spec.parse_artwork("season01-poster.jpg"), "season-poster")
    check(g, "无前缀 poster 判定（电影里不允许）", spec.is_unprefixed_artwork("poster.jpg"), True)
    check(g, "前缀式不算无前缀", spec.is_unprefixed_artwork(STEM + "-poster.jpg"), False)
    check(g, "thumb 属 Kodi 语义，保留不改名",
          spec.normalize_artwork_name("thumb.png", STEM), "thumb.png")
    check(g, "旧 logo 归一到 clearlogo",
          spec.normalize_artwork_name("logo.png", STEM), STEM + "-clearlogo.png")


def check_punctuation() -> None:
    g = "A3 标点"
    check(g, "半角冒号 → ' - '", sanitize("Dune: Part Two"), "Dune - Part Two")
    check(g, "全角冒号保留", sanitize("变形金刚2：卷土重来"), "变形金刚2：卷土重来")
    check(g, "非法字符 → '-'", sanitize("a/b*c?d"), "a-b-c-d")
    check(g, "空白折叠", sanitize("  多余  空白  "), "多余 空白")


def check_tech_labels() -> None:
    g = "A4 技术标签"
    check(g, "乱序标签按规范序重排",
          parse_media_name("Movie (2020) TrueHD Atmos 2160p.iso").tech,
          "2160p TrueHD Atmos")
    check(g, "H.265 / DV / DDP 全序",
          parse_media_name("Movie (2020) 2160p H.265 DV DDP.iso").tech,
          "2160p H.265 DV DDP")
    # 回归：曾被正则截断成 DTSHD 的坑
    check(g, "DTSHD-MA 不被截断",
          parse_media_name("Movie (2020) DTSHD-MA 1080p.iso").tech,
          "1080p DTSHD-MA")
    check(g, "DTS-X 不被截断",
          parse_media_name("Movie (2020) DTS-X 2160p.iso").tech,
          "2160p DTS-X")
    check(g, "分辨率优先（4K/UHD 归一）",
          parse_media_name("Movie (2020) UHD TrueHD.iso").resolution, "2160p")


def check_multi_version() -> None:
    g = "A5 多版本 / 多碟"
    disc = ["指环王1 2160p TrueHD Atmos DISC1", "指环王1 2160p TrueHD Atmos DISC2"]
    mv = ["Movie 1080p AC3", "Movie 2160p DTSHD-MA"]
    check(g, "多碟判为同版本", spec.is_same_version(disc), True)
    check(g, "多版本判为不同版本", spec.is_same_version(mv), False)
    check(g, "多碟公共前缀去掉碟号", spec.common_stem(disc), "指环王1 2160p TrueHD Atmos")
    check(g, "多碟候选含公共前缀",
          "指环王1 2160p TrueHD Atmos" in spec.stem_candidates(disc), True)
    check(g, "多碟海报归公共前缀",
          spec.artwork_owner("指环王1 2160p TrueHD Atmos-poster.jpg", disc),
          "指环王1 2160p TrueHD Atmos")
    check(g, "多碟 nfo 归公共前缀",
          spec.nfo_owner("指环王1 2160p TrueHD Atmos.nfo", disc),
          "指环王1 2160p TrueHD Atmos")
    check(g, "多版本各归自己那套",
          spec.artwork_owner("Movie 1080p AC3-poster.jpg", mv), "Movie 1080p AC3")
    check(g, "多版本公共前缀不冒充归属",
          spec.artwork_owner("Movie-poster.jpg", mv), "")
    # 真实版本数（多碟只算 1）—— 报表 movie_pan_versions 就取这个
    check(g, "多碟算 1 个版本", spec.count_versions(disc), 1)
    check(g, "多版本算 2 个版本", spec.count_versions(mv), 2)
    check(g, "单文件算 1 个版本", spec.count_versions(["A 1080p"]), 1)
    check(g, "空列表算 0 个版本", spec.count_versions([]), 0)
    check(g, "多碟同组", [len(x) for x in spec.version_groups(disc)], [2])
    check(g, "多版本分两组", [len(x) for x in spec.version_groups(mv)], [1, 1])


def check_containers() -> None:
    g = "A6 容器"
    for name, kind in (("合集", "container"), ("专辑", "album"),
                       ("变形金刚（系列）", "series"), ("漫威宇宙（主线）", "mainline")):
        check(g, f"{name} 是容器", spec.is_container_dir(name), True)
        check(g, f"{name} 类型 = {kind}", spec.container_kind(name), kind)
    check(g, "作品目录不是容器",
          spec.is_container_dir("大黄蜂 (2018) {tmdbid-424783}"), False)


def check_folder_parse() -> None:
    g = "A7 目录解析"
    p = parse_media_name("大黄蜂 (2018) {tmdbid-424783}", is_dir=True)
    check(g, "目录标题", p.title, "大黄蜂")
    check(g, "目录年份", p.year, "2018")
    check(g, "目录 TMDB ID", p.tmdb_id, "424783")


# ═══════════════ B. 文档一致 ═══════════════

def check_docs() -> None:
    g = "B 文档一致"
    doc_has(g, SPEC_MD, spec.SPEC_VERSION)
    doc_has(g, SPEC_MD, "冻结")
    doc_has(g, SPEC_MD, "clearlogo")
    doc_has(g, SPEC_MD, "DTSHD-MA")
    doc_has(g, SPEC_MD, "{tmdbid_tag}")
    doc_has(g, SPEC_MD, spec.MOVIE_FOLDER_TEMPLATE)

    doc_has(g, SKILL_MD, "冻结")
    doc_has(g, SKILL_MD, "clearlogo")
    doc_has(g, SKILL_MD, "tmdbid")

    doc_has(g, README_MD, "clearlogo")
    doc_has(g, README_MD, "DTSHD-MA")
    doc_has(g, README_MD, "tmdbid")


# ═══════════════ C. 配置一致 ═══════════════

def check_config() -> None:
    g = "C 配置一致"
    if not CONFIG_JSON.exists():
        _RESULTS.append((True, g, "config.json 不存在（跳过）", True, True))
        return
    try:
        cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    except Exception as e:                                  # noqa: BLE001
        _RESULTS.append((False, g, "config.json 可解析", f"解析失败: {e}", "合法 JSON"))
        return
    naming_cfg = cfg.get("naming") or {}
    pairs = (
        ("movie_folder_template", spec.MOVIE_FOLDER_TEMPLATE),
        ("tv_folder_template", spec.TV_FOLDER_TEMPLATE),
        ("season_folder_template", spec.SEASON_FOLDER_TEMPLATE),
        ("movie_file_template", spec.MOVIE_FILE_TEMPLATE),
        ("tv_file_template", spec.TV_FILE_TEMPLATE),
    )
    for key, canon in pairs:
        if key in naming_cfg:
            check(g, f"config.naming.{key} 不偏离事实源", naming_cfg[key], canon)
    cont = cfg.get("containers") or {}
    if cont.get("series_suffix"):
        check(g, "config.containers.series_suffix", cont["series_suffix"], spec.SERIES_SUFFIX)
    if cont.get("mainline_suffix"):
        check(g, "config.containers.mainline_suffix", cont["mainline_suffix"], spec.MAINLINE_SUFFIX)
    if cont.get("fixed"):
        check(g, "config.containers.fixed 覆盖固定容器",
              set(cont["fixed"]) >= {"合集", "专辑"}, True)


# ═══════════════ 主流程 ═══════════════

def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    for fn in (check_frozen_metadata, check_folder_and_file, check_artwork_and_nfo,
               check_punctuation, check_tech_labels, check_multi_version,
               check_containers, check_folder_parse, check_docs, check_config):
        fn()

    cur = ""
    for ok, group, name, got, want in _RESULTS:
        if group != cur:
            cur = group
            if not quiet:
                print(f"\n【{group}】")
        if not ok or not quiet:
            mark = "✅" if ok else "❌"
            line = f"  {mark} {name}"
            if not ok:
                line += f"\n       期望: {want!r}\n       实际: {got!r}"
            print(line)

    total = len(_RESULTS)
    failed = [r for r in _RESULTS if not r[0]]
    print("\n" + "═" * 58)
    if failed:
        print(f"❌ 规范冻结校验未通过：{total - len(failed)}/{total} 通过，{len(failed)} 项失败")
        print(f"   冻结范围：{spec.SCOPE_STATUS}（版本 {spec.SPEC_VERSION} / {spec.SPEC_FROZEN_AT}）")
        print("   若确属有意变更，请按 SPEC.md §0 的变更流程同步文档后再跑一次。")
        return 1
    print(f"✅ 规范冻结校验全部通过：{total}/{total}")
    print(f"   版本 {spec.SPEC_VERSION} · 冻结于 {spec.SPEC_FROZEN_AT} · "
          f"已冻结分类 {[k for k, v in spec.SCOPE_STATUS.items() if v == 'frozen']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
