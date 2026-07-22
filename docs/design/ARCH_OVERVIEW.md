# Architecture Overview - mcp-tavily

| 版本号 | 日期       | 变更说明 | 作者       |
|--------|------------|----------|------------|
| v1.4.0 | 2026-07-22 | 修复日志系统未捕获 app.core/app.tasks 模块日志的问题 | Copilot |
| v1.3.0 | 2026-07-22 | 传输协议改为仅支持 Streamable HTTP，移除 stdio/SSE | Copilot |
| v1.2.0 | 2026-07-22 | 修复 UsageMonitor 鉴权 Bug 及 Key 状态机死锁 Bug，补充回归测试 | Copilot |
| v1.1.0 | 2026-04-06 | 补充 ConfigManager 热加载与简单列表支持 | Gemini CLI |
| v1.0.0 | 2026-04-06 | 初始版本 | Gemini CLI |

## 1. 系统架构 (System Architecture)
(Mermaid 图表保持不变)

## 2. 技术栈 (Tech Stack)
(技术栈表保持不变)

## 3. 核心组件说明 (Component Details)

### 3.1 ConfigManager (热加载)
- **职责:** 解析环境变量 `TAVILY_API_KEYS` 并监听配置变化。
- **格式支持:** 简单逗号分隔列表，例如 `TAVILY_API_KEYS=tvly-key1,tvly-key2`。
- **热加载机制:**
  - **监听:** 监听根目录下的 `.env` 文件变更。
  - **同步:** 变更时重新解析并通知 `KeyPoolManager` 更新池，无需重启。
- **Fail-fast:** 若无有效 Key 则报错退出。

### 3.2 KeyPoolManager
- **职责:** 管理所有的 API Key，实现调度算法。
- **算法:** **Round Robin (轮询)**。
- **并发处理:** 使用 `asyncio.Lock` 确保线程安全。
- **重试逻辑:** 捕获 429/5xx 异常，自动触发 `get_next_key()` 重试。

### 3.3 Key Entity (状态机)
每个 Key 拥有以下状态：
- `ACTIVE`: 正常可用。
- `COOLDOWN`: 遇到 429 错误，进入冷却期。
- `EXHAUSTED`: 配额已耗尽。
- `ERROR`: 无效或配置错误。
- **并发安全:** 内部使用 `threading.RLock`（可重入锁）保护状态迁移。`update_usage`/
  `check_status` 会在已持有锁的情况下调用 `set_exhausted`/`set_active`，此前使用普通
  `threading.Lock` 会导致死锁（已修复）。

### 3.4 UsageMonitor (后台任务)
- **实现:** `asyncio.create_task` 启动永久循环任务。
- **逻辑:** 定期 (10min) 调用 `/usage` API 同步状态。
- **鉴权:** 每次请求使用对应 `Key.raw_key` 构造 `Authorization` 请求头（Bearer Token），
  确保配额查询针对的是真实的目标 Key（历史版本曾误用占位符导致请求恒为 401，已修复并补充回归测试
  `tests/test_monitor.py::test_sends_correct_bearer_authorization_header`）。

### 3.5 传输层 (Transport)
- **协议:** 仅支持 **Streamable HTTP**（`fastmcp` `transport="streamable-http"`），不再支持
  stdio 或 SSE。
- **配置:** 监听地址/端口/路径通过环境变量 `MCP_HOST`（默认 `0.0.0.0`）、`PORT`（默认 `8000`）、
  `MCP_PATH`（默认 `/mcp`）配置，见 `TavilyAggregator.start()`（`app/main.py`）。
- **客户端接入:** MCP 客户端需以 `url` 方式（而非 `command` 子进程方式）接入，指向
  `http://<host>:<port><path>`。

### 3.6 日志系统 (Logging)
- **架构:** `app/utils/logger.py` 的 `setup_logger()` 将滚动文件 Handler（`RotatingFileHandler`，
  5MB×5 备份）和 stderr Handler 挂载在**根 Logger**上，而非仅挂在 `mcp_tavily` 具名 Logger 上。
- **原因:** `app.core.config` / `app.core.manager` / `app.tasks.monitor` 均使用
  `logging.getLogger(__name__)` 获取独立 Logger，与 `mcp_tavily` 互不相关；历史版本仅给
  `mcp_tavily` 挂 Handler，导致这些模块的关键运行时日志（Key 池调度、冷却、配额同步、
  ConfigManager 热加载）被静默丢弃或绕过滚动文件，无法排障（已修复，回归测试见
  `tests/test_logging.py`）。
- **级别:** 根 Logger 级别读取 `LOG_LEVEL` 环境变量（默认 `INFO`），确保 INFO 级别的运行时事件
  也能被记录，而不是默认丢弃在 Python 根 Logger 的 `WARNING` 级别之下。

## 4. 数据流 (Data Flow)
(数据流说明保持不变)

## 5. 设计约束与安全 (Constraints & Security)
- **敏感信息:** 日志严禁打印完整 Key，仅显示脱敏版本 (`tvly-abcd...wxyz`)。
- **热加载响应:** 动态调整 Key 池时应保证当前正在执行的请求不受影响。

## 6. 异常处理策略 (Error Handling)
(策略表保持不变)
