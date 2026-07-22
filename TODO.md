# TODO

## 待完成
- [ ] **缺口｜官方 Schema 审计脚本缺失** - PRD 目录结构规范要求的 `scripts/sync_schemas.py`
      （对比 `npx @tavily/mcp` 输出、防止 `app/constants/tools.py` 陈旧）尚未实现 — 优先级：中 — 发现于 2026-07-22
- [ ] 动态权重调度（根据剩余配额分配权重）— 优先级：低（README 后续规划）
- [ ] 导出 Key 消耗报表 — 优先级：低（README 后续规划）
- [ ] 支持通过 MCP Tool 动态添加 Key — 优先级：低（README 后续规划）
- [ ] 支持动态添加/删除 API Key（PRD 5 后续规划）— 优先级：低（实际已通过 .env 热加载实现，PRD §5 已标注）
- [ ] 增加监控仪表盘（PRD 5 后续规划）— 优先级：低
- [ ] 让 `monitor_usage_task` 真正读取 `MONITOR_INTERVAL` 环境变量（当前硬编码 10 分钟）— 优先级：中 — 发现于 2026-07-22

## 已完成
- [x] 初始化项目结构与 GEMINI.md — 2026-04-06
- [x] 创建 GitHub 仓库 zx2015/mcp-tavily — 2026-04-06
- [x] 采用类继承方式重构 `TavilyAggregator` — 2026-04-06
- [x] 编写集成测试并验证 Round Robin 与 429 容错逻辑 — 2026-04-06
- [x] 模块化需求文档 - `docs/requirements/PRD.md`（v1.3.0）— 已存在
- [x] 架构概览 - `docs/design/ARCH_OVERVIEW.md`（v1.1.0）— 已存在
- [x] 环境搭建 - `/media/data/venv/bin/python` 可用，`pytest`/`unittest` 5 项测试通过 — 2026-07-22 验证
- [x] MCP 基础框架 - `TavilyAggregator(FastMCP)` 已实现，4 个官方工具已注册 — 已存在
- [x] Tavily API 聚合逻辑 - Round Robin + Cooldown + Usage 监控（除鉴权 Bug 外）已实现 — 已存在
- [x] `.github/copilot-instructions.md` 已创建 — 2026-07-22
- [x] **Bug 修复｜UsageMonitor 鉴权失效** - `app/tasks/monitor.py` 的 `Authorization` 头已改为使用
      真实 `key.raw_key` 构造 Bearer Token；新增 `tests/test_monitor.py`（8 个用例）覆盖鉴权头、
      usage/limit 解析、plan_limit 回退、主动熔断（EXHAUSTED）、401/网络异常处理、后台轮询循环 — 2026-07-22
- [x] **Bug 修复｜Key 状态机死锁** - `app/core/key.py` 的 `update_usage`/`check_status` 在已持有
      `self._lock` 时又调用 `set_exhausted`/`set_active`（同样加锁），普通 `threading.Lock`
      导致死锁；已改为 `threading.RLock`，回归测试 `test_marks_exhausted_when_usage_reaches_limit`
      验证通过 — 2026-07-22
- [x] **传输协议改造｜仅支持 Streamable HTTP** - 移除 `MCP_TRANSPORT`(stdio/sse) 分支逻辑，
      `TavilyAggregator.start()` 固定使用 `transport="streamable-http"`，监听地址/端口/路径
      由 `MCP_HOST`/`PORT`/`MCP_PATH` 环境变量控制（默认 `0.0.0.0:8000/mcp`）；同步更新
      `docker-compose.yml`、`README.md`、PRD/ARCH_OVERVIEW 设计文档；新增
      `tests/test_transport.py`（4 个用例）验证默认配置、环境变量覆盖、禁止 stdio/sse、
      无 Key 时拒绝启动；并将本地 `uvicorn` 由 0.30.1 升级至 `requirements.txt` 锁定的
      0.43.0（旧版本不支持 Streamable HTTP 所需的 `websockets-sansio` ws 协议，会导致启动崩溃）；
      已通过 `curl` 实测 `POST /mcp` `initialize` 请求返回 200 — 2026-07-22
- [x] **Bug 修复｜日志系统丢失核心运行时日志** - `app/utils/logger.py` 的 `setup_logger()`
      此前只给具名 Logger `mcp_tavily` 挂 Handler，而 `app/core/config.py`、
      `app/core/manager.py`、`app/tasks/monitor.py` 均使用 `logging.getLogger(__name__)`
      获取独立 Logger（如 `app.core.manager`），根 Logger 默认无 Handler 且级别为
      `WARNING`，导致 Key 池调度/冷却/配额同步/热加载等 INFO 级别日志被**静默丢弃**，
      WARNING/ERROR 级别也会绕过滚动文件、只走 Python 兜底 stderr——本地部署容器实测确认
      运行 25+ 分钟无一条相关日志。已改为将 Handler 挂载在**根 Logger**上并从 `LOG_LEVEL`
      环境变量读取级别（默认 INFO）；新增 `tests/test_logging.py`（5 个用例）验证 Handler
      挂载位置、三个模块日志均可被根 Handler 捕获、日志级别遵循 `LOG_LEVEL`；已重新构建
      容器镜像并实测 `docker logs`/`app.log` 中可见 `app.core.config`/`app.core.manager`
      日志 — 2026-07-22
- [x] **功能增强｜Key 失效日志带位置 + 末 6 位脱敏** - `app/core/key.py` 新增 `position: Optional[int]`
      字段（1-based，由 `ConfigManager` 解析 `TAVILY_API_KEYS` 时分配）和 `tail` property
      （末 6 位脱敏，不足 6 位返回全 `*`）。`app/core/manager.py` 在 401 / 429 路径输出
      `[Key失效] 第 N 个 Key（尾号 xxxxxx）...` 格式日志；`app/tasks/monitor.py` 在配额
      耗尽转换（ACTIVE→EXHAUSTED）时输出同样格式日志，且仅在状态转换时打一次以避免刷屏。
      新增 3 个回归测试覆盖三种事件 + 转换去重行为（`tests/test_integration.py::test_401/429_*`、
      `tests/test_monitor.py::test_exhausted_log_emitted_only_on_transition`）。测试套件
      25/25 通过 — 2026-07-22
