# Security Policy - mcp-tavily

> 本文档说明本项目对 **Tavily API Key** 等敏感信息的保护策略，以及一旦怀疑泄露后的处置流程。
> 文档对象：项目维护者、贡献者，以及任何部署本服务的运维人员。

## 1. 敏感信息分类

| 类别 | 示例 | 默认存储位置 | 是否进入 git |
|------|------|--------------|--------------|
| Tavily API Key | `TAVILY_API_KEYS=tvly-dev-xxxxx,...` | `.env` | ❌ 严禁 |
| 官方工具 Schema 模板 | 工具的 name/description 文本 | `app/constants/tools.py` | ✅ 公开 OK |
| 部署端口 / 监听地址 | `MCP_HOST` / `PORT` / `MCP_PATH` | `.env` 或 `docker-compose.yml` | ⚠️ 仅当端口非默认时考虑是否公开 |
| 服务真实版本号 | `serverInfo.version` | `fastmcp` 运行时给出 | ⚠️ 与文档版本号映射需对齐 |

## 2. 已部署的防御措施

### 2.1 `.gitignore` 规则（2026-07-22 加强）
```
.env          # 主配置文件
.env.*        # 所有变体（.env.local / .env.production 等）
!.env.example # 模板必须被追踪；`!` 否定规则放行
```
**生效验证**：
- `git ls-files | grep ^.env` 仅返回 `.env.example`，无其它变体；
- 创建临时 `.env.local` 不会被 `git status` 报告为未追踪；
- 修改 `.env.example` 仍正常进入 `git status`，确认模板未被误排除。

### 2.2 运行时日志脱敏
- `app/core/key.py::_mask_key()`：仅输出 `tvly-abcd...wxyz` 形式（前 4 + 后 4），完整 Key 永不进入 `app.log`。
- `app/utils/logger.py`：旋转文件 + stderr，所有日志经根 Logger 统一输出，避免散落到默认 Python stderr 绕过持久化。

### 2.3 失败 Key 自动熔断
- 任何 Tavily 401 / Unauthorized / Invalid 响应会立即将对应 Key 标记为 `ERROR` 状态（`app/core/manager.py:69`），并切换到下一个 Key 重试——无效 Key 不再被持续消耗。

### 2.4 失效日志的脱敏边界（v3.4.4+）

服务在三种"Key 失效"事件中会输出带位置和末 6 位的日志，便于用户定位：

| 暴露字段 | 用途 | 暴露风险 |
|----------|------|----------|
| `Key.position`（1-based） | 告诉用户"是 .env 中的第几个 Key" | 0 风险——位置不依赖 Key 内容 |
| `Key.tail`（末 6 位） | 让人工在 `.env` 中对位 | 🟡 低——末 6 位提供 ~36 bits 熵的子集；用于对位而非鉴权，攻击者无收益 |

**末 6 位不可用于**：
- ❌ 恢复完整 Key（末 6 位仅为原 Key 的一小段）
- ❌ 作为鉴权凭据（Tavily 要求完整 Key 匹配）
- ❌ 在多个服务间"凭记忆同步"

**末 6 位可用于**：
- ✅ 在多行 `.env` 中快速锁定是哪个 Key 失效
- ✅ 在团队沟通时引用"配置中那个以 `xyz123` 结尾的 Key"
- ✅ 与 Tavily Dashboard 的 Key 列表末位对照

如对末 6 位仍有顾虑，可将 `app/core/key.py::tail` 改为返回 `key.raw_key[-4:]` 即可收紧——单行修改。

## 3. 已知泄露面（请逐条确认）

> ⚠️ 这部分列出了 Key **可能** 离开本地可信环境的渠道。请逐条检查你的部署环境：

| 渠道 | 风险等级 | 处置建议 |
|------|----------|----------|
| 工作区 `.env` 文件本身 | 🟢 中（若机器多用户 / 备份被同步） | 文件权限 `chmod 600`，避免在共享目录 |
| 容器日志（`docker logs` / `app.log`） | 🟡 中 | 已在 v3.4.4 修复（根 Logger 接管），历史日志需手工清理 |
| 终端 history（`history` / `fish_history`） | 🟡 中 | 部署前清空；不要把 `TAVILY_API_KEYS=...` 整行敲进 shell |
| 截图 / 录屏 | 🟡 中 | 截图前先用脱敏值或隐藏 |
| 远程 SSH 会话录像 | 🟠 较高 | 企业环境常见；定期轮换 |
| 第三方日志聚合（Sentry / Datadog / Loki） | 🟠 较高 | 部署时务必配置脱敏规则，禁止上报请求体 |
| CI/CD runner 缓存 | 🟠 较高 | 临时环境部署完毕后立即清理 runner 缓存 |
| 团队协作的 IDE 配置同步（Settings Sync） | 🟠 较高 | 关闭 `.env` 同步；只同步 `launch.json` 这类不含值的文件 |

## 4. 怀疑泄露后的应急响应（Incident Response）

### 4.1 第一步：轮换 Key（**< 5 分钟**）
1. 登录 [Tavily Dashboard](https://app.tavily.com/) → API Keys。
2. **删除** 全部疑似泄露的 Key（不要先创建新的，否则旧 Key 仍在生效窗口内被消费）。
3. **生成** 新 Key，记录到本地密码管理器（**不要写进 .env**——直到 §4.2 完成后）。
4. 在 Tavily 控制台查看旧 Key 的最后使用时间，确认是否仍有人继续消费（若消费立即归零，说明攻击者已主动失效）。

### 4.2 第二步：清理本地痕迹（**< 30 分钟**）
- 删除 `.env` 中旧 Key，更新为新 Key。
- `git reflog expire --expire=now --all && git gc --prune=now`（**仅当旧 Key 曾进入 git 历史**才需要——本项目 `.env` 从未进 git，可跳过）。
- 检查本地 `/var/log/`、`~/.bash_history`、`~/.zsh_history`、`~/.local/share/fish/`、`/tmp/` 下是否有泄露残留。
- 容器重建：`docker-compose down && docker-compose up -d --build`，确保新 Key 生效。

### 4.3 第三步：审计与监控（**< 24 小时**）
- 在 Tavily 控制台开启 **Usage Alert**（若支持），配额消耗异常时邮件告警。
- 在本服务侧：
  ```bash
  # 检查日志中 Key 状态变更
  grep -E "Key .* (hit rate limit|is invalid|usage synced)" app.log
  ```
- 检查是否有非预期 IP / 地区调用 Tavily API（Tavily Dashboard → Activity）。

### 4.4 第四步：文档与团队同步（**< 48 小时**）
- 在团队群组通告事件经过、时间线、处置结果。
- 在 `TODO.md` 中追加高优先级条目跟踪后续改进（如引入密钥管理服务）。

## 5. 长期建议（Roadmap）

> 这些是**尚未实现**的硬化措施，详见 `TODO.md`。

- [ ] **接入密钥管理服务**：使用 HashiCorp Vault / AWS Secrets Manager / 1Password CLI 注入 `TAVILY_API_KEYS`，避免 `.env` 落到磁盘。
- [ ] **运行时鉴权**：在 `TavilyAggregator.start()` 之后增加 Bearer Token 校验，仅允许授权的 MCP 客户端调用。
- [ ] **请求日志脱敏中间件**：在 `app/main.py` 增加出站/入站日志过滤，确保任何新字段都不会泄露 Key。
- [ ] **官方 Schema 审计脚本**：`scripts/sync_schemas.py` 防止 `app/constants/tools.py` 偏离官方描述（同时避免有人误把鉴权字段塞进 Schema）。
- [ ] **CI 隐私检查**：在 GitHub Actions 中跑 `gitleaks` / `trufflehog`，阻断任何 `.env` 误提交。

## 6. 报告安全问题

如果你发现了本项目中的真实安全漏洞，**请勿**通过公开 issue 报告。
请联系仓库所有者：[GitHub @zx2015](https://github.com/zx2015)（建议先用 GitHub 私信建立私下渠道）。

---

**最后更新**: 2026-07-22（与文档同步 review 同步）
**适用范围**: mcp-tavily v3.4.4+