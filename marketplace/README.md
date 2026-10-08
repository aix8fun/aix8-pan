# 上架材料（连接器市场）

本目录是提交 WorkBuddy 连接器市场的打包骨架，符合开放平台「MCP + Skill」结构：

```
marketplace/
├── connector-meta.json   # 连接器元信息（名称/描述/示例/auth_mode/minWorkbuddyVersion）
├── mcp.json              # MCP Server 连接配置（${VAR} 占位符 ← 表单字段 key）
├── token-schema.json     # 用户勾选连接器时弹出的配置表单定义
└── icon.svg              # 市场图标
```

## 认证方式：用户自填 Token（auth_mode: token）

用户在市场勾选本连接器时，WorkBuddy 会弹出 `token-schema.json` 定义的表单，
收集 5 个字段（OpenList 地址/用户名/密码 + TMDB 地址/Key）。
凭证仅保存在用户本机 `~/.workbuddy`，不经过云端；stdio 模式下以环境变量
注入子进程——与 `aix8pan/config.py` 的 `OPENLIST_*` / `TMDB_*` 读取逻辑一一对应，
**工程侧零改动**。

## 提交前必须完成的事

- [ ] **打包发布 PyPI**：`mcp.json` 目前假设 `uvx aix8-pan` 可拉到包（需 `pyproject.toml`
      + console 入口，见工程根 TODO）。未发布前此命令不可用。
- [ ] `connector-meta.json` 与 `token-schema.json` 中的 GitHub 地址换成真实仓库。
- [ ] 附上 `skills/aix8-pan/SKILL.md`：把现有 SKILL.md 改写为**分发行形态**
      （去掉本机绝对路径 `~/WorkBuddy/aix8-pan`、`data/plans` 等引用）。
- [ ] `icon.svg` 如需更好看的设计自行替换（当前为占位：云 + 胶片条）。
- [ ] 按「提交前检查」清单自查后打包整个目录提交 WorkBuddy 团队审核
      （开放平台注册入口：open.workbuddy.cn）。

## 本机开发联调

上架前本机仍按工程根 README「部署引导」的 mcp.json 形态注册（绝对路径 + 明文 env），
与本目录互不影响。
