# AIX8-Pan 命名规范 v2.1

> 本规范**从用户 115 网盘既有 tMM 整理存量反向提炼**，不是凭空设计。
> 代码里的唯一事实源是 `aix8pan/naming_spec.py`，本文档是它的自然语言说明。
> 任何命名疑问以 `naming_spec.py` 为准；两者不一致时改代码改文档。

**最高优先级原则：少改名 / 零重命名。** 存量已合规的形态一律承认，绝不为了「更漂亮」而全库重命名。

---

## 0. 规范状态（冻结声明）

| 项 | 值 |
|---|---|
| 版本 | **v2.2**（v2.1 → v2.2：剧集规则冻结——目录带 `{tmdbid-N}`、单集真实集名+方括号技术标签） |
| 冻结日期 | 2026-10-07（电影）/ 2026-10-08（剧集） |
| **已冻结范围** | **电影（movie）、剧集（tv）** —— 用户已确认满意，规则不再随讨论漂移 |
| 草案范围 | 动画 / 纪录片 / 音乐 / 电子书（待逐条确认后冻结） |
| 唯一事实源 | `aix8pan/naming_spec.py`（`SPEC_VERSION` / `SCOPE_STATUS` / `FROZEN_MOVIE_RULES`） |
| 守门校验 | `python3 tests/check_spec.py`（破坏规则即 FAIL，退出码非 0） |

### 电影冻结条款（逐条）

| 条款 | 冻结值 |
|---|---|
| 作品目录 | `{title} ({year}) {tmdbid_tag}` → `大黄蜂 (2018) {tmdbid-424783}` |
| 主文件 | `{title} {original} ({year}) [{tech}]` → `大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso` |
| artwork | **前缀式** `{主文件主体}-poster.jpg` / `-fanart.jpg` / `-clearlogo.png` |
| artwork 关键字 | `poster` / `fanart` / `clearlogo` —— **是 `clearlogo` 不是 `logo`；是 `fanart` 不是 `backdrop`** |
| NFO | 与主文件**同名**（不是 `movie.nfo`） |
| 技术标签 | 段序 `分辨率 → 片源 → 视频编码 → HDR → 音频编码 → Atmos`；**技术段整体包方括号 `[…]`（分辨率随段进括号），段内空格分隔** |
| 字幕 | `{主文件主体}.zh-CN.srt` / `.en.srt` —— 语言码**点号**分隔（Emby/Kodi 业界约定） |
| 标点 | 半角冒号 `:` → ` - `；**全角冒号 `：` 保留** |
| 多版本 | 多版本各自成套 artwork/nfo；多碟/分卷取**公共前缀** |
| ID 位置 | ID 只出现在**目录名**，文件名不带 ID |

### 变更流程（改冻结规则必须走完这 4 步）

1. 改 `aix8pan/naming_spec.py`（唯一事实源）
2. 同步本文档与 `SKILL.md` 的速查表
3. 跑 `tests/check_spec.py` + `tests/test_parser_naming.py`（必须全绿）
4. 跑 `scripts/run_audit.py /115/01-电影`，确认存量仍全合规（幂等）

> 冻结不是「不能改」，而是**改之前必须显式走完上面 4 步**——避免规则在讨论中悄悄漂移，
> 导致已经整理好的库被重新命名一遍。

---

## 1. 目录层级模型

```
/115/                                    根
├── 01-电影/                              分类根  {NN}-{中文名}
│   ├── 0-待整理/                          收件箱（临时落点，会被排空）
│   ├── 合集/                              ┐
│   │   └── 变形金刚（系列）/                 │ 组织容器（不参与整理，只作命名空间）
│   │       └── 变形金刚 (2007) {tmdbid-1858}/   ← 作品目录
│   │   └── 漫威宇宙（主线）/                 │
│   │       └── 钢铁侠（系列）/               │
│   │           └── 钢铁侠 (2008) {tmdbid-1726}/
│   ├── 专辑/                              │
│   │   └── 大黄蜂 (2018) {tmdbid-424783}/
│   └── 沙丘2 (2024) {tmdbid-693134}/        ← 直接平铺的作品
├── 02-剧集/
│   └── 白夜追凶 (2017)/
│       └── Season 01/                    季目录
├── 03-动画/   04-纪录片/   12-乡村剧/ …
└── AA-TODO/                              待整理区（收件箱别名）
```

### 容器 vs 作品

| 类型 | 判定 | 处理 |
|---|---|---|
| 收件箱 | 名字 ∈ {`0-待整理`, `待整理`, `AA-TODO`} | 默认**排空**：内部作品搬进目标库 |
| 系列容器 | 以 `（系列）` 结尾 | **不动**（只报告） |
| 主线容器 | 以 `（主线）` 结尾 | **不动** |
| 固定容器 | 名字 ∈ {`合集`, `专辑`} | **不动** |
| 作品目录 | 目录内直接含媒体文件 | 参与整理 |

> 需要处理容器内部时，直接指定其内部路径（如 `/115/01-电影/专辑`），
> 或用 `build_plan(include_containers=true)` 下钻。

---

## 2. 命名规则表

> **电影相关各行（L1 电影目录 / L2 电影文件 / L3 电影伴随文件与 NFO）已于 v2.0 冻结**（见 §0）；
> **剧集相关各行已于 v2.2 冻结**（2026-10-08：目录带 `{tmdbid-N}`、单集真实集名+方括号技术标签）。

| # | 对象 | 规则 | 存量样板 |
|---|---|---|---|
| L0 | 分类根 | `{NN}-{中文名}` | `01-电影` |
| L1 | 电影作品目录 | `{中文标题} ({年份}) {tmdbid-N}` | `大黄蜂 (2018) {tmdbid-424783}` |
| L1 | 剧集作品目录 | `{中文标题} ({年份}) {tmdbid-N}` — v2.2 起**带 ID** | `三国演义 (1994) {tmdbid-72645}` |
| L1.5 | 季目录 | `Season {NN}`（两位补零） | `Season 01` |
| L1.9 | 系列容器 | `{系列名}（系列）` 全角括号 | `变形金刚（系列）` |
| L1.9 | 主线容器 | `{系列名}（主线）` 全角括号 | `漫威宇宙（主线）` |
| L2 | 电影主文件 | `{中文标题} {英文原名} ({年份}) [{技术标签}].{ext}` | `大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso` |
| L2 | 剧集文件 | `{标题} - S{NN}E{NN} - {真实单集标题} [{技术标签}].{ext}` | `三国演义 - S01E01 - 桃园三结义 [2160p WEB-DL H265 AAC].mp4` |
| L3 | 电影伴随文件 | **前缀式**：`{主文件主体}-{artwork}.{ext}` | `大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos]-poster.jpg` |
| L3 | 电影 NFO | 与主文件**同名** | `大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].nfo` |
| L3 | 电影字幕 | `{主文件主体}.{语言码}.srt`，语言码点号分隔 | `大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].zh-CN.srt` |
| L3 | 剧集伴随文件 | **无前缀固定名**（放剧集根目录） | `poster.jpg` `fanart.jpg` `clearlogo.png` `season01-poster.jpg` `tvshow.nfo` |

### 两条容易踩的细节

1. **电影与剧集的 artwork 形态不同** —— 这不是笔误：
   - 电影目录里只有一个主文件 → artwork 用**前缀式**（Plex/Kodi local artwork 惯例）
   - 剧集目录里有很多集 → artwork 用**无前缀固定名**放剧集根目录
2. **artwork 关键字是 `clearlogo` 不是 `logo`**；背景图统一叫 `fanart`（不是 `backdrop`）。
   存量一律如此，旧名会在整理/刮削时被归一。

---

## 3. 作品文件名细则

### 3.1 电影

```
{中文标题} {英文原名} ({年份}) {技术标签}.{ext}
```

- 中文标题与英文原名之间是**一个空格**（不是 ` - `）
- 英文原名**只在原文为拉丁文字时出现**（`latin_title()` 判定）；
  存量里 `少年的你 少年的你 (2019)` 属旧工具把中文标题重复两遍的产物，**规范上不重复**
- 文件名**不带** `{tmdbid-N}` 标识 —— ID 只出现在**目录名**
- 技术标签空格分隔、**无方括号**

### 3.2 剧集

```
{标题} - S{NN}E{NN} - {单集标题}.{ext}
```

- 这是 tMM 的标准形态，也是存量 `白夜追凶 - S01E01 - 第1集.mp4` 的形态
- **不带年份、不带技术标签**（存量可核实的规范样本如此）
- 缺单集标题时自动省略末段：`太平年 - S01E13.mp4`

### 3.3 季节/集号写法

- 季目录：`Season 01`（两位补零）
- 集号：`S01E01`（两位季 + 两位集）

### 3.4 多版本 / 多碟（artwork 前缀归属）

一个作品目录里出现多个媒体文件时，先判定它们属于**同一版本**还是**多版本共存**：

| 情形 | 样本 | `is_same_version` | artwork / nfo 前缀 |
|---|---|---|---|
| 多碟 · 同版本 | `… 2160p TrueHD Atmos DISC1.iso` + `… DISC2.iso` | ✅ 是 | **公共前缀**（去掉碟号）：`… 2160p TrueHD Atmos-poster.jpg` |
| 分卷 · 同版本 | `Movie.2020.1080p.BluRay.Part1` + `.Part2` | ✅ 是 | 同上 |
| **多版本共存** | `… 1080p AC3.iso` + `… 2160p DTSHD-MA.iso` | ❌ 否 | **每个版本自成一整套**，各自 `-poster` / `-fanart` / `-clearlogo` / `.nfo` |

铁律：

- **绝不把多版本并成一个公共前缀**。`007：大战皇家赌场 Casino Royale (2006)-poster.jpg`
  这种前缀在库里**根本不存在对应主文件**，属于错误产物。
- 多版本目录里，每个版本**各自**带齐 poster / fanart / clearlogo / nfo 即为合规；
  个别版本缺海报只提示「该版本缺海报」，不影响其他版本。
- 无前缀式（`poster.jpg`）在**电影**目录里一律判 `ART_MOVIE_UNPREFIXED`（只有剧集才用无前缀）。

> 落到代码：`naming_spec.stem_candidates()` 给出合法前缀候选集（多碟时含公共前缀），
> `artwork_owner()` / `nfo_owner()` 用**最长前缀匹配**把每个伴随文件定位到它所属的版本。

---

## 4. 技术标签

段序**固定**，空段整段消失（不留双空格）；分隔符是**空格**：

```
分辨率  片源  视频编码  HDR  音频编码  Atmos
```

| 段 | 规范写法 | 别名归一 |
|---|---|---|
| 分辨率 | `2160p` `1080p` `720p` `4320p` | `4K`/`UHD`→`2160p`；`2K`/`1080i`→`1080p`；`8K`→`4320p` |
| 片源 | `BluRay` `BluRay REMUX` `REMUX` `BDMV` `WEB-DL` `WEBRip` `HDTV` `BDRip` `DVDRip` | `Blu-ray`→`BluRay`；`WEBDL`→`WEB-DL` |
| 视频编码 | `H.264` `H.265` `AV1` | `x265`/`HEVC`→`H.265`；`x264`/`AVC`→`H.264` |
| HDR | `HDR10+` `HDR10` `HDR` `DV` `HLG` `SDR` | `DoVi`/`Dolby Vision`/`杜比视界`→`DV` |
| 音频编码 | `TrueHD` `DTSHD-MA` `DTSHD-HRA` `DTSHD` `DTS-X` `DTS` `DDP` `DD` `AC3` `EAC3` `AAC` `FLAC` `LPCM` `Opus` | `DTS-HD MA`/`DTSHD MA`→`DTSHD-MA`；`DTS:X`/`DTSX`→`DTS-X`；`DD+`→`DDP` |
| Atmos | `Atmos` | `全景声`/`杜比全景声`→`Atmos` |

> **音频写法以存量为准**（tMM 风格）：全库实测 51 部 `DTSHD-MA`、32 部 `DTS-X`、4 部 `DTS` ——
> 不是 `DTS-HD MA` / `DTS:X`。规范必须**顺着存量**写，否则会引发 80+ 文件的全库重命名。

**Atmos 独立成段、保留**（存量 `2160p TrueHD Atmos` 证明它不该被丢弃）。
**流媒体平台名（NF/AMZN/DSNP…）不进文件名**（存量 `2160p.NF.WEB-DL` 归一为 `2160p WEB-DL`）。

存量样本恰好只有「分辨率 + 音频」两段（因为源是蓝光原盘 ISO，名里没别的信息），
规范是**超集**：解析到什么就写什么，段序恒定。

---

## 5. 非法字符与标点

| 原字符 | 处理 | 依据（存量实测字节） |
|---|---|---|
| 半角冒号 `:` | → ` - ` | `Dune: Part Two` → `Dune - Part Two` |
| 全角冒号 `：` | **保留** | `变形金刚2：卷土重来`、`古墓丽影：源起之战` |
| `\ / * ? " < > \|` | → `-` | 文件名安全 |
| 连续空白 | 折叠为单个空格 | |
| 首尾空格与点 | 剔除 | |
| 长度 | 超 235 字节按字节截断（保留扩展名） | 网盘安全上限 |

---

## 6. 「已整理」判定（幂等关键）

判定**不重命名**的条件（`_file_acceptable(lenient=True)`）：

- **电影**：文件名里的年份与作品年份一致即可 → 不动
  （存量英文名、简写名、旧式标签一律不折腾）
- **剧集**：季集号能解析出来即可 → 不动
- **目录**：目录名以 `{标题} ({年份})` 开头，尾部为空或恰好是 ID 标识 → 认作已整理
- **季目录名等价**：`Season 1` ≡ `Season 01` ≡ `S1`，不因补零重命名

结果：`白夜追凶`（61 文件）`三国演义`（84 文件）重新规划 = **0 动作**。

---

## 7. 偏差问题码（`audit_library` 输出）

| code | 级别 | 含义 |
|---|---|---|
| `FOLDER_NO_ID` | error | 电影目录缺 `{tmdbid-N}` |
| `FOLDER_ID_LEGACY` | error | 标识写作 `{tmdb-N}`，应为 `{tmdbid-N}` |
| `FOLDER_ID_POS` | warn | 年份之后有多余内容 |
| `FOLDER_NO_YEAR` | error | 目录名缺年份 |
| `FOLDER_TITLE_GAP` | warn | 标题与 `(年份)` 之间缺空格（`小猪佩奇(2004)`） |
| `FOLDER_HAS_TECH` | error | 目录名掺入技术信息 |
| `FOLDER_EXTRA_SEG` | warn | 标题后多出版本修饰词（`… - IMAX` / `… - Theatrical Edition`） |
| `FOLDER_NO_CJK` | warn | 标题段无中文（用了 TMDB 原名） |
| `FOLDER_TV_NO_ID` | warn | 剧集目录缺 tmdbid 标识（v2.2 起必带） |
| `FILE_HAS_ID` | warn | 文件名带 ID 标识 |
| `FILE_HAS_BRACKET` | warn | 技术标签用了方括号 |
| `FILE_NO_YEAR` | error | 电影文件名缺年份 |
| `FILE_TECH_ORDER` | warn | 技术标签顺序非规范 |
| `ART_MOVIE_UNPREFIXED` | error | 电影海报为无前缀式 |
| `ART_LEGACY_KEYWORD` | error | artwork 关键字过时（`logo.png`） |
| `ART_TV_PREFIXED` | error | 剧集根目录图片为前缀式 |
| `NFO_MOVIE_GENERIC` | warn | nfo 未与主文件同名 / 剧集 nfo 非 `tvshow.nfo` |
| `ART_MISSING` / `NFO_MISSING` | warn/info | 缺海报 / 缺 nfo |
| `NO_MEDIA` | warn | 目录里没有媒体文件 |

---

## 8. 存量违规名的归一（`normalize_names`）

「少改名」不等于「永不改名」。下面这几类是**规范明确禁止**的结构，属于旧工具留下的瑕疵，
规划器会主动纠正（`build_plan(normalize_names=true)`，默认开）：

| 现象 | 归一动作 | 影响面（实测） |
|---|---|---|
| 目录用旧式 `{tmdb-N}` 标识 | 目录改名 → `{tmdbid-N}`（1 次动作） | 6 个目录 |
| 文件名带 `{tmdbid-N}` 标识 | 去掉 ID（ID 只允许出现在目录名） | 5 个文件 |
| 文件名技术标签包方括号 `[1080p]` | 去掉方括号，改空格分隔 | 5 个文件 |

**判定边界很窄**：只有「名字里出现 ID 标识」或「方括号里出现技术 token」才触发。
存量里合规的英文原名、简化命名、`DISC1` 碟号、原始发布名**一律不动**。
实测：`01-电影` 全库 277 个作品，需要归一的仅 6 个目录 / 5 个文件；
`专辑` 15 部、`白夜追凶` 61 集、`三国演义` 84 集复核仍为 **0 动作**。

artwork 前缀取**主文件改名后的**公共前缀 —— 所以主文件归一后，海报/nfo 会一起跟着改，
不会出现「海报前缀还是旧名」的错位。

### 8.1 定向纠正（`canonical_folder` / `use_tmdb_title` / `title_override`）

默认策略是「信任存量」：目录名里已有「标题 (年份)」就沿用，绝不因为标题与 TMDB 不一致
而重命名（保护 `星球大战前传1/2/3`、`无间道2/3` 这类**有意的系列编排**）。

要**定向**纠正某个明确违规的作品时，用这三个开关（默认关）：

| 开关 | 作用 | 用例 |
|---|---|---|
| `canonical_folder=true` | 忽略「源名已合规」与「目标库已有同作品目录」两条复用捷径，**强制按模板重算**目录名 | `碟中谍6：全面瓦解 - IMAX (2018)` → 去掉版本修饰词；`变形金刚：超能勇士崛起 (2023)` → 补 `{tmdbid-N}` |
| `use_tmdb_title=true` | 标题改用 **TMDB 官方标题**（覆盖目录名解析结果） | `007之太空城` → `007：太空城` |
| `title_override="…"` | 手工指定标题（**优先级最高**，用于 TMDB 中文库缺译名） | `Spider-Man - No Way Home` → `蜘蛛侠：英雄无归`；`Black Widow` → `黑寡妇` |

**整目录搬移（含目录改名）**：当组内文件最终位置都在目标目录内、且相对子路径不变时，
只发 **1 个 `move_dir`**（顺带改名），文件改名作为随后的 `rename` 动作在新目录内完成 ——
**不预建目标目录**（避免「先 mkdir 目标名、再 move_dir 改名」两者撞名）。

## 9. 配置项（`config.json → naming`）

```json
{
  "movie_folder_template": "{title} ({year}) {tmdbid_tag}",
  "tv_folder_template":    "{title} ({year})",
  "season_folder_template":"Season {season:02d}",
  "movie_file_template":   "{title} {original} ({year}) [{tech}]",
  "tv_file_template":      "{title} - {season_ep} - {episode_title}",
  "normalize_artwork":     true
}
```

模板变量：`{title}` `{original}` `{year}` `{season}` `{episode}` `{season_ep}`
`{tech}` `{tmdb_id}` `{tmdbid_tag}` `{episode_title}` `{episode_title_seg}`。
空值变量连同相邻分隔符与包裹括号整段剔除。

---

## 10. 115 / OpenList 平台行为（实测踩坑，改代码前必读）

以下都是 2026-10-07 在 `/115/AA-TODO/.panbutler-e2e` 沙盒里**复现过**的行为，
不是推测。它们决定了「先删后传」「不预建目标目录」这些实现选择。

| 现象 | 实测结论 | 代码对策 |
|---|---|---|
| **同名重复文件** | 115 **允许**同一目录下存在多个**完全同名**的文件；对已存在路径 `PUT` **不覆盖**，而是**再建一条同名条目** | 覆盖必须先删（`upload(overwrite=True)`） |
| **列表折叠同名** | `/api/fs/list` 把同名条目折叠成**一条**（只返回其中一个），重复在接口侧**不可见**，只有 115 网页端能看到两条 | 覆盖后要**回读确认**删干净，否则宁可报错 |
| **`remove` 按名删** | 一次只删掉其中一条；要彻底清干净需重复调用 | `upload` 里删 3 轮 + 回读校验 |
| **`rename` 不认全名** | 驱动只取新名的**基名**（去掉最后一段扩展名），再拼回**源文件的扩展名**：`p.txt` → rename 到 `hello.nfo` 实际得到 `hello.txt` | `rename()` 已加守卫：跨扩展名直接报错 |
| **最终一致** | `move` 之后立刻 `rename` 会报 `object not found`（重试 6 秒仍不可靠） | 跨目录搬移时**先在原地改名再 `move`** |
| **目录列表缓存** | 关键路径上必须 `refresh=true`，否则会拿到陈旧条目（曾导致「幽灵作品目录」） | 一律 `refresh=True` |

> 已经产生的同名重复，用 `scripts/dedupe_same_name.py` 检测与修复
> （思路：下载可见条目 → 按名 `remove` 让藏着的浮出来 → 保留体积较大的一份回传）。
> 注意**不能用改名探针检测** —— 见上表 `rename` 那条。

---

## 11. 目录深链（115 cid）

115 网页端的目录深链只有一种形式：

```
https://115.com/?cid=<cid>&offset=0&mode=wangpan
```

**cid 是 115 的内部目录 ID，OpenList 完全拿不到**（`/api/fs/list`、`/api/fs/get`
都不返回 id，连 `/api/fs/dirs` 也没有），所以只能走 115 官方接口自取。

`scripts/fetch_115_cids.py` 的做法：

1. **就地解密本机 Chrome 的 Cookie 库**（`~/Library/Application Support/Google/Chrome/
   <profile>/Cookies`，只读；AES 密钥取自 macOS 钥匙串的 *Chrome Safe Storage*，
   PBKDF2-SHA1 / 1003 轮 / 16 字节，v10 前缀）。
   ⚠️ 复制 profile 目录是**没用的** —— UID / CID / SEID / KID 都是**会话型 cookie**，
   新起的浏览器实例一定是未登录状态。
2. 调 `https://webapi.115.com/files?...&cid=<cid>&show_dir=1` 逐层下钻，
   **只沿目标目录的祖先链**走（262 个作品只需 ~60 次请求）。
3. 按 `n`（名字）精确匹配认领子目录，得到每个作品目录的 cid，拼成深链。

调用要点：必须带 `Cookie` + 桌面版 `User-Agent` + `Referer/Origin: https://115.com`，
否则会被 WAF 挡下（返回 405 的 HTML 页，不是 JSON）。
校验方式：用 cid 反查目录内容，逐文件核对名字与体积是否与库内一致。


