# AIX8-Pan — 个人网盘 AI 助手 × 影视库整理刮削

挂在 WorkBuddy 里的 115 网盘 AI 工具，一个连接器两重身份：

- **个人网盘 AI 工具**：自然语言列目录、全局搜索、取下载直链、查看作品技术信息
- **影视资源整理刮削工具**：「识别 → 规划 → 确认 → 执行 → 刮削 → 审计」全流程，  
  **不下载文件内容**，只通过 OpenList 的文件操作 API 完成

> 命名规则不是凭空设计的：全部从你网盘里已有的 tMM 整理存量**反向提炼**，  
> 详见 **[SPEC.md](SPEC.md)**（代码里的事实源是 `aix8pan/naming_spec.py`）。  
> **规则状态：v2.2，「电影」（2026-10-07）与「剧集」（2026-10-08）规则均已冻结**（用户确认满意）——  
> 改动必须走 SPEC.md §0 的变更流程，并用 `python3 tests/check_spec.py` 守门。

```
WorkBuddy 对话界面
   │
   ├── Skill: aix8-pan           ← 命名规范 + 工作流 + 安全纪律（方法论层）
   │
   └── MCP 连接器: aix8-pan      ← 14 个原子工具（能力层）
          │
          ├── naming_spec        命名规范单一事实源（模板/artwork/技术标签序；电影已冻结 v2.0）
          ├── OpenListClient     列目录 / 建目录 / 移动 / 改名 / 上传 / 直链 / 删除
          ├── TMDBClient         搜索 / 详情 / 单集 / 图片下载
          ├── Planner            只读扫描 → 解析 → 匹配 → 生成方案 JSON
          ├── Executor           限速执行方案（断点续跑）
          ├── Scraper            海报 / fanart / clearlogo / NFO 上传（按规范命名）
          └── Auditor            只读审计，报告与命名规范的偏差
          │
          ▼
      OpenList（Cookie 挂载 115 个人网盘，挂载路径 /115）
```

## 快速开始

```bash
cd ~/WorkBuddy/aix8-pan

# 1. 自检
python3 -c "import sys;sys.path.insert(0,'.');from aix8pan.config import load_config;from aix8pan.openlist import OpenListClient as C;from aix8pan.tmdb import TMDBClient as T;c=load_config();
ol=c['openlist'];t=c['tmdb'];print(len(C(ol['base_url'],ol['username'],ol['password']).list_all('/115')),'项根目录');print('TMDB ok' if T(t['api_key'],t['api_host'],t['image_host']).available else 'TMDB 未配置')"

# 2. 规范冻结守门校验（改了规则/文档后必跑，全绿才算没破坏冻结）
python3 tests/check_spec.py

# 3. 单元测试（解析/命名/规范，44 项，无网络）
python3 tests/test_parser_naming.py

# 3b. MCP 服务契约测试（工具注册 / outputSchema / annotations / 返回信封，无网络）
python3 tests/test_server_contract.py

# 4. 库审计（只读，报告偏差）
python3 scripts/run_audit.py /115/01-电影

# 5. 端到端测试（在网盘沙盒内跑，结束自动清理）
python3 tests/test_e2e_write.py

# 6. 「合集 / 专辑」规范核对表（只读 → xlsx）
python3 scripts/scan_containers.py && python3 scripts/make_report2.py
#    想要「目录链接」列（115 深链）再多跑一步：
#    解密本机 Chrome 的 115 登录态换取各目录的 cid（只读，不碰网盘）
<venv>/bin/python scripts/fetch_115_cids.py && python3 scripts/make_report2.py

# 6b. TMDB × 115 对照表（分「合集 / 专辑」两个 sheet + 系列汇总）
<venv>/bin/python scripts/fetch_tmdb_collections.py   # TMDB 合集归属 + 成员 + 官网链接
python3 scripts/fetch_inbox.py                        # 只读列「0-待整理」，区分“没资源/没归位”
python3 scripts/make_report2.py                       # → 合集_专辑_TMDB核对表.xlsx

# 7. 定向纠正：按核对表问题清单改名 + 补海报（无 --execute 只预览）
python3 scripts/fix_issues.py --execute
```

在 WorkBuddy 里用自然语言驱动即可，例如：

**网盘日常**

- 「看看我 115 网盘根目录有什么」
- 「帮我在 115 里搜一下沙丘相关的文件」
- 「把这部片子的下载直链给我」

**影视整理与刮削**

- 「把 /115/云下载 里刚下完的片子整理进电影库，先给我看方案再动手」
- 「审计一下 /115/01-电影，哪些不符合命名规范」
- 「01-电影 里哪些片子缺海报？帮我逐个补上」
- 「给 沙丘2 (2024) {tmdbid-693134} 刮一下海报」

## 命名规范速查（完整版见 SPEC.md）

> **电影、剧集规则均已冻结 v2.2**（电影 2026-10-07 / 剧集 2026-10-08，用户确认满意）；动画等仍为草案。

| 层级     | 规则                                                      | 账面样板                                                                         |
| ------ | ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 电影作品目录 | `{中文标题} ({年份}) {tmdbid-N}`                              | `大黄蜂 (2018) {tmdbid-424783}`                                                 |
| 剧集作品目录 | `{中文标题} ({年份}) {tmdbid-N}`（v2.2 起带 ID）                  | `三国演义 (1994) {tmdbid-72645}`                                                 |
| 季目录    | `Season {NN}`                                           | `Season 01`                                                                  |
| 电影主文件  | `{中文标题} {英文原名} ({年份}) [{技术}].{ext}`                     | `大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].iso`                              |
| 剧集文件   | `{标题} - S{NN}E{NN} - {真实单集标题} [{技术}].{ext}`             | `三国演义 - S01E01 - 桃园三结义 [2160p WEB-DL H265 AAC].mp4`                          |
| 电影海报   | **前缀式** `{主文件主体}-poster.jpg`                            | `…Atmos]-poster.jpg` / `-fanart.jpg` / `-clearlogo.png`                      |
| 电影 NFO | 与主文件**同名**                                              | `大黄蜂 Bumblebee (2018) [2160p TrueHD Atmos].nfo`                              |
| 剧集海报   | **无前缀固定名**（剧集根目录）                                       | `poster.jpg` `fanart.jpg` `clearlogo.png` `season01-poster.jpg` `tvshow.nfo` |
| 技术标签   | 技术段整体包方括号、段内空格分隔、段序固定                                   | `[2160p TrueHD Atmos]`                                                       |
| 音频写法   | **顺着存量**：`DTSHD-MA` / `DTS-X`（不是 `DTS-HD MA` / `DTS:X`） | 全库 51 部 `DTSHD-MA`、32 部 `DTS-X`                                              |
| 容器     | `{系列名}（系列）` / `{系列名}（主线）`                               | `变形金刚（系列）` `漫威宇宙（主线）`                                                        |

三条铁律：

1. **目录只装身份**（标题 + 年份 + 可选 ID），技术信息只出现在文件名。
2. **电影、剧集目录都带 `{tmdbid-N}`**（v2.2 起统一）；**文件名一律不带 ID**，技术段都包方括号（tech 为空时方括号整段消失）。存量旧形态（无方括号、`第1集` 式集名）按「少改名」原则不追改。
3. **标点**：半角冒号 `:` → `-`，全角冒号 `：` **保留**（`变形金刚2：卷土重来`）。

## 幂等与「少改名」设计（本项目的核心取舍）

每次改名/移动都是一次网盘 API 调用，几千次会触发限流。因此整理器**不追求把库刷成统一格式**：

| 情形                     | 行为                             |
| ---------------------- | ------------------------------ |
| 目标库已有同作品目录             | 复用其名字（不重建、不改名）                 |
| 源目录名已合规 `标题 (年份)`      | **整目录一次搬移**（1 个 API 调用），内部文件不动 |
| 文件已在正确目录且身份对得上         | 跳过（英文名、格式简化版都不动）               |
| 文件不在正确位置 / 身份对不上       | 才改名                            |
| artwork 形态非规范          | **只在本来就要动这个目录时**顺手归一（不额外制造重命名） |
| 组织容器（合集/专辑/（系列）/（主线））  | 默认不动，只报告                       |
| 收件箱（`0-待整理`/`待整理`） | 默认排空，内部作品搬进目标库                   |
| 无法归类的文件（.txt、压缩包）      | 保持原位，仅在方案中报告                   |
| 重复执行同一方案               | 断点续跑，已完成的动作跳过                  |

实测：对已整理的剧集（白夜追凶 61 文件、三国演义 84 文件）重新规划 = **0 个动作**。

## 平台约束（115 / OpenList 实测踩坑）

这几条是本工程**已内置规避**的硬约束，改代码时别踩回去：

| 现象                                                              | 规避方式                                                                 |
| --------------------------------------------------------------- | -------------------------------------------------------------------- |
| `POST /api/fs/move` 在**同一父目录**下会被判成「源已在目标中」，报 `file [x] exists` | 同父改名走 `POST /api/fs/rename`；跨目录才用 `move`（`executor.move_dir` 已分流）    |
| `PUT /api/fs/put` 对**已存在文件**返回成功但内容不变（静默无操作）                    | 需要覆盖时**先 `remove` 再 `put`**（`OpenListClient.upload(overwrite=True)`） |
| 目录列表会返回**陈旧缓存**，导致读到已被改名的旧目录名（曾产出「幽灵记录」）                        | 所有关键读取一律 `refresh=True`（审计、季目录下钻、`_find_works`）                      |
| 目录状态是**最终一致**：刚 move 完立刻 rename 可能报「对象不存在」                      | 改名带退避重试；报「已存在」则视为已就位（幂等）                                             |
| 整目录搬移若先 `mkdir` 目标名再 `move_dir` 改名 → **两者撞名**                   | `_finalize` 判定「整目录搬移」后**不预建目标目录**，只发 1 个 `move_dir` + N 个 `rename`   |

## 安全机制

1. **Plan / Execute 硬分离**：`build_plan` 全程只读，方案落盘 `data/plans/<plan_id>.json`；  
   `execute_plan` 必须显式传 `confirm=true`，否则只做预检（dry-run）。
2. **审计器只读**：`audit_library` 只 list + 比对，不产生任何写动作。
3. **限速**：所有写操作间隔 ≥ `op_interval_ms`（默认 700ms）。
4. **批量上限**：单次执行动作数上限 `max_execute_batch`（默认 200）。
5. **失败可续**：动作级状态记录，失败中断后可重跑同方案继续。
6. **不误删**：空目录清理前会等待并强刷确认目录确实为空，且仅清理「确有文件被搬走」的目录。
7. **不覆盖存量**：刮削已存在的产物一律跳过（除非显式 `force=true`）。  
   注意：库内 nfo 是 tMM 富信息版（含完整 cast/crew，20–35 KB），本工具生成的是  
   精简版 —— **对已有 nfo 用 force 属于信息降级**，除非明确知道在做什么。

## 配置

**凭据走环境变量，不进 config.json**（config.json 是纯环境描述，可分享可备份）：

| 环境变量 | 用途 | 注入位置 |
|---|---|---|
| `AIX8PAN_OPENLIST_PASSWORD` | OpenList 登录密码 | `~/.workbuddy/mcp.json` 的 `aix8-pan.env` |
| `AIX8PAN_TMDB_API_KEY` | TMDB API Key | 同上 |

优先级：环境变量 > `config.json`（文件里写了会被 env 覆盖；env 为空回落文件值）。
手动跑脚本/测试时可 `export AIX8PAN_OPENLIST_PASSWORD=...` 或临时写回 config.json。

`config.json`：

```jsonc
{
  "openlist": { "base_url": "...", "username": "admin", "op_interval_ms": 700 },
  "tmdb":     { "api_host": "https://tmdb.aws360.cn", "language": "zh-CN" },
  "paths":    { "movies": "/115/01-电影", "tv": "/115/02-剧集", "anime": "/115/03-动画" },
  "naming":   { "movie_folder_template": "...", "tv_folder_template": "...",
                "movie_file_template": "...", "tv_file_template": "...",
                "normalize_artwork": true },
  "containers": { "series_suffix": "（系列）", "mainline_suffix": "（主线）",
                  "fixed": ["0-待整理", "合集", "专辑"],
                  "inbox": ["0-待整理", "待整理"] },
  "limits":   { "max_execute_batch": 200 }
}
```

- `openlist.op_interval_ms`：**写操作最小间隔，防风控。默认 700ms，不建议调小。**
- `naming.*_template`：命名模板，变量  
  `{title} {original} {year} {season} {season_ep} {episode} {tech} {tmdb_id} {tmdbid_tag} {episode_title} {episode_title_seg}`；  
  变量为空时连同相邻分隔符/括号一起省略。

## 目录结构

```
aix8-pan/
├── config.json              # 配置（凭据已迁 mcp.json env，此文件无秘密）
├── SPEC.md                  # ★ 统一命名规范（从存量提炼）
├── aix8-pan/
│   ├── naming_spec.py       # ★ 命名规范单一事实源（模板/artwork/技术标签/容器）
│   ├── config.py            # 配置加载
│   ├── openlist.py          # OpenList REST 客户端（token 自动续期 + 限速）
│   ├── parser.py            # 文件名解析（标题/年份/SxxExx/规范序技术标签/TMDB ID）
│   ├── naming.py            # 命名引擎（模板渲染 + 空值剔除 + 标点规范化 + artwork 命名）
│   ├── tmdb.py              # TMDB 客户端（搜索/详情/单集/图片，带缓存）
│   ├── planner.py           # 规划器（只读；容器识别 + 幂等 + artwork 归一）
│   ├── executor.py          # 执行器（限速执行 + 断点续跑）
│   ├── scraper.py           # 刮削器（按规范命名上传海报/nfo）
│   ├── auditor.py           # ★ 库审计器（只读，输出偏差清单）
│   └── server.py            # MCP stdio 服务（14 个工具）
├── data/
│   ├── plans/               # 方案存档
│   └── cache/               # TMDB 查询缓存
└── tests/
    ├── check_spec.py          # ★ 规范冻结守门校验（行为契约 + 文档一致 + 配置一致）
    ├── test_parser_naming.py  # 44 项单元测试
    ├── test_server_contract.py # MCP 契约测试（工具注册 / outputSchema / annotations / 信封）
    ├── run_audit.py           # 库审计脚本
    ├── scan_containers.py     # 只读扫描「合集/专辑」全部作品 → JSON
    ├── make_report.py         # JSON → 规范核对表 xlsx（24 列，含文件总数 / 115 目录链接）
    ├── fetch_115_cids.py      # 解密本机 Chrome 的 115 登录态 → 目录 cid → 115 深链
    ├── fetch_tmdb_collections.py # 逐片取归属合集 + 合集成员/上映情况 + 官网 canonical 链接
    ├── fetch_inbox.py         # 只读列「0-待整理」，供区分“没资源”与“没归位”
    ├── make_report2.py        # JSON → TMDB×115 对照表 xlsx（合集/专辑双 sheet + 系列汇总）
    │                          #   注意：movie_pan_versions = 真实版本数（多碟只算 1，见 naming_spec.count_versions）
    ├── dedupe_same_name.py    # 检测 / 清理 115 上的同名重复条目
    ├── verify_titles.py       # 全量与 TMDB 官方标题比对
    ├── fix_issues.py          # 定向纠正（改名 + 补海报），无 --execute 只预览
    └── test_e2e_write.py      # 端到端（沙盒写入 + 自动清理）
```

## MCP 工具一览（14）


所有工具返回**统一信封** `{ok, data}` / `{ok, error}`（TypedDict `Result`），  
并发布 **outputSchema** —— 结果同时写入 `structuredContent`（宿主可结构化消费）  
与文本 JSON（向后兼容）。危险工具带 `destructiveHint`，只读工具带 `readOnlyHint`。

| 分组 | 工具                                                           |
| -- | ------------------------------------------------------------ |
| 浏览 | `list_dir` `search_files` `get_paths` `get_download_url`     |
| 识别 | `parse_name` `naming_spec` `tmdb_search` `tmdb_detail`       |
| 整理 | `build_plan` `preview_plan` `execute_plan`（需 `confirm=true`） |
| 刮削 | `scrape_dir`（可 `cleanup_legacy` 归一旧式图片）                      |
| 审计 | `audit_library`（只读）                                          |
| 运维 | `health_check`                                               |

## 后续可扩展（架构已预留）

- **ffprobe 真实媒体信息**：`get_download_url` 已可用，接 `ffprobe -print_format json <url>`  
  做 Range 读头即可（每文件几 MB 流量），结果可回填技术标签
- **一键整改**：把 `audit_library` 的偏差清单直接转成 Plan（如 `{tmdb-N}` → `{tmdbid-N}` 目录改名）
- **定时巡检**：配合 WorkBuddy 自动化，每周扫描待整理区自动生成方案
- **多盘支持**：OpenList 侧换成其它网盘驱动，本工程代码零改动
