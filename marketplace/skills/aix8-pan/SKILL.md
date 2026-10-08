---
name: aix8-pan
description: 115 个人网盘 AI 助手 + 影视资源整理刮削工具（基于 OpenList 桥接）。网盘日常（列目录、按关键字搜文件、取下载直链、查某部片的技术信息），或整理/归档/重命名电影、剧集、动画、纪录片，刮削海报/nfo，检查命名是否规范，审计媒体库，批量改名时使用。关键词：115、网盘、个人网盘、搜文件、直链、整理、归档、入库、刮削、海报、nfo、TMDB、电影、剧集、命名规范、命名规则、Season、待整理、重命名、审计、OpenList。
user-invocable: true
---

# 115 个人网盘 AI 助手 × 影视整理刮削（AIX8-Pan）

一个连接器两重身份：**个人网盘 AI 工具**（列目录 / 搜索 / 直链 / 查技术信息）+
**影视资源整理刮削工具**（用 **Plan → 确认 → Execute** 的流程管理媒体库）。
整理与刮削都通过 `aix8-pan` MCP 连接器暴露的原子工具完成，本 Skill 负责「怎么整理」的方法论与安全纪律。

**命名规则的唯一事实源在服务端 `naming_spec` 工具里。**
任何命名疑问先调 `naming_spec` 取值，不要凭记忆。

> **规则状态（v2.2）：电影、剧集已冻结**，动画/纪录片等仍为草案。
> `naming_spec` 返回里的 `scope_status` / `frozen_movie_rules` 就是当前冻结态。
> 处理**电影**时一律按冻结条款执行，不要把规则「优化」成别的样子。

## 一、可用工具（MCP 连接器 `aix8-pan`）

| 工具 | 用途 | 是否写盘 |
|---|---|---|
| `health_check` | 连通性自检（OpenList + TMDB） | 否 |
| `get_paths` | 获取配置的库路径映射 | 否 |
| `list_dir(path, refresh)` | 列目录 | 否 |
| `search_files(parent, keywords)` | 搜索 | 否 |
| `get_download_url(path)` | 取直链（ffprobe 等后续用途） | 否 |
| `parse_name(name, is_dir)` | 解析文件名（标题/年份/SxxExx/规范序技术标签） | 否 |
| `naming_spec()` | 取统一命名规范（模板 / artwork 命名 / 技术标签序 / 容器规则） | 否 |
| `tmdb_search(title, year, media_type)` | TMDB 搜索候选 | 否 |
| `tmdb_detail(tmdb_id, media_type)` | TMDB 详情 | 否 |
| `build_plan(source, target_root, media_type, include_containers, drain_inbox)` | **只读**扫描并生成整理方案 | 否（只写本地方案存档） |
| `preview_plan(plan_id)` | 查看方案全文（含每条动作） | 否 |
| `execute_plan(plan_id, confirm)` | 执行方案 | **是** |
| `scrape_dir(work_dir, media_type, tmdb_id, force, cleanup_legacy)` | 刮削海报/nfo | **是** |
| `audit_library(root, media_type, include_containers)` | **只读**审计命名规范偏差 | 否 |

## 二、库路径约定

用 `get_paths` 读取（默认值如下，用户可在本机偏好文件中自定义）：

| 键 | 默认值 | 含义 |
|---|---|---|
| `movies` | `/115/01-电影` | 电影库 |
| `tv` | `/115/02-剧集` | 剧集库 |
| `anime` | `/115/03-动画` | 动画库 |
| `doc` | `/115/04-纪录片` | 纪录片库 |

## 三、命名规范速查（电影、剧集已冻结 v2.2 · 完整版以 `naming_spec` 工具返回为准）

```
L0  分类根      {NN}-{中文名}                       01-电影 / 02-剧集
L1  作品目录    {中文标题} ({年份}) {tmdbid-N}        电影 大黄蜂 (2018) {tmdbid-424783}
                （电影、剧集统一带 ID，v2.2 起）       剧集 三国演义 (1994) {tmdbid-72645}
L1.5 季目录     Season {NN}                         Season 01
L1.9 容器       {系列名}（系列） / {系列名}（主线）    变形金刚（系列） / 漫威宇宙（主线）
                固定容器：合集 / 专辑  ·  收件箱：0-待整理 / 待整理
L2  作品文件
                电影 {中文标题} {英文原名} ({年份}) [{技术}].{ext}
                     大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso
                剧集 {标题} - S{NN}E{NN} - {真实单集标题} [{技术}].{ext}
                     三国演义 - S01E01 - 桃园三结义 [2160p WEB-DL H265 AAC].mp4
L3  伴随文件
                电影 **前缀式**：{主文件主体}-poster.jpg / -fanart.jpg / -clearlogo.png
                     nfo 与主文件同名：{主文件主体}.nfo
                剧集 **无前缀固定名**（放剧集根目录）：
                     poster.jpg / fanart.jpg / clearlogo.png / season01-poster.jpg / tvshow.nfo
```

**技术标签**：段内空格分隔、**技术段整体包方括号 `[…]`**（分辨率随段进括号；
tech 为空时方括号整段消失），段序固定
`分辨率 → 片源 → 视频编码 → HDR → 音频编码 → Atmos`，空段整段消失。
例：`[2160p TrueHD Atmos]`、`[2160p H.265 DV DDP]`。
`4K/UHD→2160p`，`x265/HEVC→H.265`，`DoVi/Dolby Vision/杜比视界→DV`，
`全景声/杜比全景声→Atmos`；流媒体平台名（NF/AMZN…）不进文件名。

**标点**：半角冒号 `:` → ` - `；**全角冒号 `：` 保留**（`变形金刚2：卷土重来`）。

**五条铁律**

1. **目录只装身份**（标题 + 年份 + ID），绝不掺技术信息 —— 否则同一部片的不同版本会分裂成多个目录
2. **电影、剧集目录都带 `{tmdbid-N}`**（v2.2 起统一）；**文件名一律不带 ID**，技术段都包方括号
3. 剧集必须有 `Season XX` 子目录 + `SxxExx` 令牌；单集用 TMDB 真实集名（缺集名时省略末段）
4. 电影 artwork 用**前缀式**、剧集 artwork 用**无前缀固定名**；关键字是 `clearlogo` 不是 `logo`
5. **少改名**：已有目录/文件只要身份对得上就不动它（存量旧形态如无方括号、`第1集` 集名，
   因「少改名」原则**不追改**，详见第五节）

## 四、标准工作流

### 场景 A：把散乱目录整理进库

```
1. list_dir("/115/云下载")              先看清有什么（任何散乱目录都行）
2. build_plan("/115/云下载/xxx")       → 得到 plan_id + 摘要（此时网盘零改动）
3. preview_plan(plan_id)               把动作清单完整展示给用户
4. 用户明确同意后 → execute_plan(plan_id, confirm=true)
```

> 若源目录里有 `0-待整理` 这类收件箱子目录，`build_plan` 默认会一并排空；
> 没有就忽略，不影响流程。

### 场景 B：给作品刮削海报

```
scrape_dir("/115/01-电影/沙丘2 (2024) {tmdbid-693134}")
→ 电影：上传 {主文件主体}-poster.jpg / -fanart.jpg / -clearlogo.png + {主文件主体}.nfo
→ 剧集：上传 poster.jpg / fanart.jpg / clearlogo.png / season01-poster.jpg / tvshow.nfo
（已存在的自动跳过）
```

若该电影目录里是**旧式无前缀图片**（`poster.jpg` / `logo.png` / `movie.nfo`），
加 `cleanup_legacy=true` 会在生成规范图片后删掉旧文件，完成形态归一。

### 场景 C：新增资源入库

```
1. list_dir("/115/云下载")                     找到下载完的目录
2. build_plan("/115/云下载/xxx", target_root="/115/01-电影")
3. 展示方案 → 用户确认 → execute_plan
4. scrape_dir(整理后的目录)                     顺手刮削
```

### 场景 D：审计库里有多少不符合规范

```
audit_library("/115/01-电影")     → 逐作品报告偏差码 + 修改建议（全程只读）
```

会下钻 `合集/专辑/（系列）/（主线）`。用户问「我的命名规范是什么」时，
调 `naming_spec` 并把结果整理成表讲给他。

## 五、幂等与「少改名」纪律（务必向用户说明）

整理器已内置保守策略，**不追求把库刷成统一格式**，因为每次改名都是一次网盘 API 调用（有风控风险）：

- 目标目录已存在同作品 → **复用它的名字**，不重建、不改名
- 源目录名已合规（`标题 (年份)`）→ **整体搬移**，一个动作搞定，内部文件一个都不改名
- 文件已在正确目录 + 标题/年份/集号对得上 → **跳过**（哪怕它是英文名或格式简化版）
- 只有「不在正确位置」或「身份对不上」的文件才改名
- **artwork 形态归一也是「顺带」的**：只在本来就要动这个目录时才顺手统一，绝不为了统一形态而额外制造重命名
- 组织容器（`合集`/`专辑`/`（系列）`/`（主线）`）→ **默认不动**，只在方案里报告
- 收件箱（`0-待整理`/`待整理`）→ **默认排空**，内部作品搬进目标库
- 无法归类的文件（`.txt`、压缩包等）→ **保持原位**，只在方案里报告

对同一批文件重复跑 `build_plan` 应当得到接近零动作的方案 —— 这是健康信号。若发现大量改名的方案，先问用户是否真的要批量改名。

## 六、安全纪律（不可违背）

1. **禁止直接改文件**：永远先 `build_plan`（只读）→ 展示 → 用户**明确同意** → 才 `execute_plan(confirm=true)`。
   `preview_plan` 的结果必须展示给用户，不能自己看了就执行。
2. **审计不写盘**：`audit_library` 永远只读；不要把它报告的偏差直接拿去批量执行，要先跟用户确认。
3. **批量动作留眼**：方案含 `renames` 超过 100 时，明确提示用户「这会触发 N 次网盘 API 调用，可能触发限流，建议分批」。
4. **不碰媒体库以外的东西**：默认只在用户指定的目录内操作。
5. **不动用户的刮削产物**：`scrape_dir` 对已存在的 poster/nfo 自动跳过；只有用户明确要求「覆盖」时才传 `force=true`。
   删除旧式图片（`cleanup_legacy=true`）必须单独跟用户确认。
6. **限速是保护**：所有写操作间隔默认 700ms，**不要建议用户调小**。
7. **失败要如实报告**：`execute_plan` 返回的 `errors` 要原样转达，不要淡化。

## 七、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `health_check` 报 OpenList 错 | 服务挂了 / 115 挂载失效 / 未配置 | 先看 issues 逐项提示：缺 `OPENLIST_URL` → 用户还没部署 OpenList（引导见仓库 README「部署引导」，github.com/OpenListTeam/OpenList）；缺账号 → 在连接器配置里补 `OPENLIST_USER`/`OPENLIST_PASS`；连接失败 → OpenList 服务掉线或 115 挂载失效，让用户去 OpenList 后台重挂 |
| TMDB 报错 | key 失效 / 地址不可达 | 检查连接器配置的 `TMDB_API_KEY` 与 `TMDB_HOST`；国内可用官方地址或自建代理（github.com/aix8fun/tmdb-proxy） |
| 方案里大量 `unmatched` | 目录名无年份且 TMDB 未匹配 | 展示给用户，请其确认标题年份；或用 `tmdb_search` 手工找 ID |
| 目标目录被重复创建 | 网盘目录缓存滞后 | 已内置强刷；若仍出现，稍等重跑 `build_plan` |
| 改名后源目录没被删除 | 目录内有未归类文件 | 正常行为（安全设计），方案里会列出这些文件 |
| 审计耗时较长 | 逐作品强刷列目录 | 正常；缩小 `root` 范围可加速 |

## 八、参考

- 开源仓库：<https://github.com/aix8fun/aix8-pan>（README 部署引导 / SPEC.md 命名规范全文）
- **命名规范**：以 `naming_spec` 工具返回为唯一标准（电影、剧集 v2.2 已冻结）
- **连接配置**：勾选连接器时表单填写的 `OPENLIST_URL` / `OPENLIST_USER` / `OPENLIST_PASS` / `TMDB_HOST` / `TMDB_API_KEY`（仅存本机）
- 方案存档：自动保存在用户本机数据目录（执行审计轨迹，可回溯每个方案动过哪些文件）
