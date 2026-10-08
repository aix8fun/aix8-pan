# 上架材料（连接器市场）

本目录是提交 WorkBuddy 连接器市场的打包骨架，符合开放平台「MCP + Skill」结构：

```
marketplace/
├── connector-meta.json      # 连接器元信息（名称/描述/示例/auth_mode/minWorkbuddyVersion）
├── mcp.json                 # MCP Server 连接配置（${VAR} 占位符 ← 表单字段 key）
├── token-schema.json        # 用户勾选连接器时弹出的配置表单定义
├── icon.svg                 # 市场图标
└── skills/aix8-pan/SKILL.md # 分发行 Skill（方法论与安全纪律，无本机路径）
```

## 认证方式：用户自填 Token（auth_mode: token）

用户在市场勾选本连接器时，WorkBuddy 会弹出 `token-schema.json` 定义的表单，
收集 5 个字段（OpenList 地址/用户名/密码 + TMDB 地址/Key）。
凭证仅保存在用户本机 `~/.workbuddy`，不经过云端；stdio 模式下以环境变量
注入子进程——与 `aix8pan/config.py` 的 `OPENLIST_*` / `TMDB_*` 读取逻辑一一对应。

## 启动方式：git 直装（无需 PyPI）

`mcp.json` 使用 `uvx --from git+https://github.com/aix8fun/aix8-pan@v1.1.0 aix8-pan`，
用户机器只需装有 `uv`，无需 pip/PyPI。**发新版时**：打新 tag → 更新本文件
里的 tag 引用 → 重新提交审核。

以后若发布 PyPI，可简化为 `"args": ["aix8-pan"]`（本地构建验证已就绪：
`uv build` 产出 wheel，入口命令 `aix8-pan`，uvx 冒烟握手通过）。

## 提交审核前检查清单

- [x] 打包配置：`pyproject.toml` + console 入口 `aix8-pan`（`uv build` 已验证）
- [x] 真实仓库地址：github.com/aix8fun/aix8-pan（token-schema docUrl 指向 README 部署引导）
- [x] 分发行 SKILL.md：`skills/aix8-pan/SKILL.md`（无本机绝对路径；命名规范以 naming_spec 工具为唯一标准）
- [x] 图标：云 + 播放键 App 风格（marketplace 尺寸 64px 下清晰可辨）
- [x] 推送 tag `v1.1.0` 到仓库（mcp.json 引用了它，已验证 ls-remote 可见）
- [ ] 按官方「提交前检查」自查后，将本目录打包提交 WorkBuddy 团队审核
      （开放平台：open.workbuddy.cn，审核通过后通常 10–15 分钟内同步市场）

## 本机开发联调

上架前本机仍按工程根 README「部署引导」的 mcp.json 形态注册（绝对路径 + 明文 env），
与本目录互不影响。发行模式下数据目录自动锚定到 `~/.aix8pan/`（避免写进 uv 缓存区），
可用环境变量 `AIX8PAN_DATA_DIR` 覆盖。
