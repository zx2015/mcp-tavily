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

> 📌 **§1 实际内容（2026-07-22 同步）**:
> 整体采用**两层代理 + 异步监控**的架构:
>
> 1. **传输层（Streamable HTTP）**: 由 `FastMCP.run(transport="streamable-http", ...)` 暴露
>    `POST /mcp` 端点，对 MCP 客户端表现为标准 MCP 服务器。
> 2. **业务层（TavilyAggregator）**: 继承 `FastMCP`，在 `__init__` 中初始化 `ConfigManager`、
>    `KeyPoolManager`、注册 4 个工具方法、注册 lifespan 启动后台监控任务。
> 3. **核心层（KeyPool + Key）**: `KeyPoolManager` 维护 Key 列表与 Round Robin 索引；
>    `Key` 是带状态机的实体（`ACTIVE` / `COOLDOWN` / `EXHAUSTED` / `ERROR`），用 `RLock` 保护。
> 4. **基础设施层**: `ConfigManager` 监听 `.env` 文件变化实现热加载；`monitor_usage_task`
>    协程定期调用 `https://api.tavily.com/usage` 同步配额。
>
> 关键约束: 所有运行时日志必须沿 Logger 层级传播到根 Logger 才能被持久化与展示（见 §3.6）。

## 2. 技术栈 (Tech Stack)
(技术栈表保持不变)

> 📌 **§2 实际技术栈（2026-07-22 同步）**:
>
> | 层 | 选型 | 说明 |
> |----|------|------|
> | MCP 框架 | `fastmcp==3.2.0`（`requirements.txt` 锁定） | 暴露 Streamable HTTP 端点 |
> | Tavily SDK | `tavily-python==0.7.23` | `tavily-search` / `extract` / `crawl` / `map` 全部走官方 SDK |
> | HTTP 客户端 | `httpx>=0.28` | Usage 监控走 `https://api.tavily.com/usage` |
> | ASGI 服务器 | `uvicorn==0.43.0` | 由 `fastmcp` 启动；**注意**: 0.30.x 不支持 Streamable HTTP 所需 ws 协议，会导致启动崩溃 |
> | 容器 | `python:3.12-slim` | 见 `Dockerfile` |
> | 配置 | 自实现 `ConfigManager` | 监听 `.env` 文件 mtime，不依赖 `python-dotenv`（运行时） |

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
- **位置 (`position`)**: v3.4.4 起新增 `position: Optional[int]` 字段（1-based），由
  `ConfigManager._parse_keys()` 在解析 `TAVILY_API_KEYS` 时分配。用于在失效日志中输出
  "第 N 个 Key"，便于用户在 `.env` 中定位。`.env` 热加载时会随 `update_keys()` 重新分配。
- **末 6 位脱敏 (`tail`)**: v3.4.4 起新增 `tail` property，仅返回 Key 末 6 位
  （不足 6 位时返回全 `*`）。**与 `_mask_key` 的"前 4...后 4"格式不同**：
  `tail` 只暴露末 6 位以避免反向推断完整 Key，但足够用于在 `.env` 中人工对位。

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

### 3.7 客户端接入 (Client Integration)

- **协议:** MCP Streamable HTTP（`POST /mcp`）。
- **接入端点（按部署方式）**:
  - Docker 部署: `http://<host>:18000/mcp`（`docker-compose.yml` 端口映射 `18000→8000`）。
  - 本地裸跑: `http://127.0.0.1:8000/mcp`（默认 `MCP_HOST=0.0.0.0` / `PORT=8000` / `MCP_PATH=/mcp`）。
- **MCP 客户端配置示例（Cursor / Claude Desktop 等）**:
  ```json
  {
    "mcpServers": {
      "mcp-tavily": {
        "url": "http://127.0.0.1:8000/mcp",
        "transport": "streamable-http"
      }
    }
  }
  ```
- **健康检查 / 探活命令**:
  ```bash
  curl -s -X POST http://127.0.0.1:8000/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"1.0"}}}'
  ```
  正常响应中应包含 `serverInfo.name == "mcp-tavily"`。

## 4. 数据流 (Data Flow)
(数据流说明保持不变)

> 📌 **§4 实际数据流（2026-07-22 同步）**:
>
> **A. 工具调用路径（同步 / 阻塞）**:
> ```
> MCP Client
>   └─ POST /mcp {jsonrpc:"tools/call", name:"tavily-search", arguments:{...}}
>        └─ FastMCP 路由 → TavilyAggregator.tavily_search(...)
>             └─ KeyPoolManager.execute_with_retry(_call)
>                  ├─ for attempt in range(len(keys)):
>                  │     └─ get_next_key()   # Round Robin + 跳过 COOLDOWN/EXHAUSTED/ERROR
>                  │          └─ Key.check_status()  # 持有 RLock 内部调用 set_active
>                  │     └─ try: TavilyClient(api_key).search(...)
>                  │     └─ except:
>                  │           ├─ "429" / "rate limit" → Key.set_cooldown(60s)
>                  │           ├─ "401" / "unauthorized" / "invalid" → Key.status = ERROR
>                  │           └─ raise (若已重试完所有 Key)
>                  └─ return result
> ```
>
> **B. 配置热加载路径（异步 / 文件监听）**:
> ```
> editor → write .env
>   └─ ConfigManager._watch() 线程: 5s 间隔检查 mtime
>        └─ reload(): 解析 TAVILY_API_KEYS，去重后比较新旧列表
>             └─ 若变化 → callback(KeyPoolManager.update_keys)
>                  └─ KeyPoolManager._keys = new_keys, _index = 0
> ```
>
> **C. 配额监控路径（异步 / 周期）**:
> ```
> lifespan() 启动 → asyncio.create_task(monitor_usage_task)
>   └─ while True:
>        ├─ keys = keys_provider()
>        ├─ await asyncio.gather(*[check_key_usage(k) for k in keys])
>        │     └─ GET https://api.tavily.com/usage
>        │     └─ key.update_usage(usage, limit)   # 持有 RLock 内部可能调用 set_exhausted/set_active
>        └─ await asyncio.sleep(interval_minutes * 60)  # 默认 10 分钟
> ```

## 5. 设计约束与安全 (Constraints & Security)
- **敏感信息:** 日志严禁打印完整 Key，仅显示脱敏版本 (`tvly-abcd...wxyz`)。
- **热加载响应:** 动态调整 Key 池时应保证当前正在执行的请求不受影响。

## 6. 异常处理策略 (Error Handling)
(策略表保持不变)

> 📌 **§6 实际异常处理策略（2026-07-22 同步）**:
>
> | 触发条件 | 识别方式（`str(e).lower()`） | 状态机动作 | 重试行为 | 失效日志（v3.4.4+） |
> |----------|------------------------------|------------|----------|---------------------|
> | Tavily 429 限流 | 包含 `429` 或 `rate limit` | `set_cooldown(60s)` → `COOLDOWN` | 立即换下一个 ACTIVE Key 重试 | `WARNING: [Key限流] 第 N 个 Key（尾号 xxxxxx）触发限流，进入 60s 冷却` |
> | Tavily 401 / 无效 Key | 包含 `401` / `unauthorized` / `invalid` | `status = ERROR` | 立即换下一个 ACTIVE Key 重试；ERROR 不会被自动恢复 | `ERROR: [Key失效] 第 N 个 Key（尾号 xxxxxx）鉴权失败，已标记为 ERROR` |
> | 5xx / 网络异常 | 其余 `Exception` | 状态不变 | 立即换下一个 ACTIVE Key 重试 | 维持原 `Key {label} failed` 简洁 warning |
> | 用尽所有 Key | `tried_keys` 覆盖池 | — | 抛出原始最后一次异常 | — |
> | 池中无 ACTIVE Key | `get_next_key()` 返回 `None` | — | 抛 `RuntimeError("No active API keys available in the pool.")` | — |
> | `.env` 中无 Key | 启动时 | — | 启动 `start()` 阶段 `logger.error(...)` + `sys.exit(1)`（fail-fast） | — |
> | Usage 401 | `response.status_code == 401` | 不变 | 仅记 ERROR 日志，不重试（避免对无效 Key 风暴） | `ERROR: [Key失效] 第 N 个 Key（尾号 xxxxxx）使用情况查询返回 401（鉴权失败）` |
> | Usage 网络异常 | `httpx` 异常 | 不变 | 仅记 ERROR 日志，下个周期再试 | 原 `Error checking usage for Key {label}: {e}` |
> | **配额耗尽 (EXHAUSTED)** | `usage >= limit > 0`（由 Usage Monitor 检测） | `set_exhausted()` | 不重试，由 Round Robin 自然跳过 | `ERROR: [Key失效] 第 N 个 Key（尾号 xxxxxx）配额耗尽 (usage/limit)，已标记为 EXHAUSTED`（**仅在状态转换时打一次**） |

## 7. 已知限制与差距 (Known Limitations & Gaps)

> 本节列出**已识别但尚未修复**的差距，作为后续工作的索引。
> 完整待办列表见 [`TODO.md`](../../TODO.md)。

### 7.1 文档↔实现差距（2026-07-22 review）
- **`MONITOR_INTERVAL` 环境变量未生效**: `.env.example` 与 `docker-compose.yml` 默认模板列出
  `MONITOR_INTERVAL=10`，但 `app/tasks/monitor.py::monitor_usage_task` 的 `interval_minutes` 参数
  硬编码为 `10`，**未读取该环境变量**。若用户调小/调大该值，实际行为不会变化。
- **官方 Schema 审计脚本缺失**: `docs/requirements/PRD.md` §2.3 与 §4 要求的
  `scripts/sync_schemas.py`（对比 `npx @tavily/mcp` 输出）尚未实现，存在 `app/constants/tools.py`
  长期偏离官方定义的风险。
- **日志按天轮转未实现**: PRD §2.4 要求"按天或按大小"，当前仅实现按大小轮转（5MB×5）。
- **服务版本号口径**: README/PRD/ARCH 各有独立版本表；运行时 `serverInfo.version`
  与文档版本号未建立映射关系（应通过构建/CI 同步）。

### 7.2 协议与部署限制
- **传输协议**: 仅支持 Streamable HTTP（`fastmcp transport="streamable-http"`），不提供
  stdio 或 SSE；接入必须用 `url` 而非 `command`。
- **鉴权**: 服务自身无任何鉴权/OAuth/API Key 校验，部署时需依赖网络层隔离。
- **容器内 Python**: `python:3.12-slim`（见 `Dockerfile`）。本地开发约定使用
  `/media/data/venv` 虚拟环境（与 `CLAUDE.md` 全局约定一致）。
- **uvicorn 版本**: `requirements.txt` 锁定 `uvicorn==0.43.0`。旧版 0.30.x 不支持 Streamable HTTP
  所需的 `websockets-sansio` ws 协议，会导致服务启动崩溃；升级前请先验证。

### 7.3 数据与状态
- **`.env` 真实 Key 不应入库**: `.env` 文件当前包含真实 Tavily API Key，已被本地 git 历史追踪
  若干次。强烈建议在 .gitignore 强化、并将已泄露的 Key 在 Tavily 控制台轮换。
- **ERROR 状态不会自动恢复**: `Key.status = KeyStatus.ERROR` 后，仅当 `update_usage(usage, limit)`
  检测到 `usage < limit` 时才会回到 ACTIVE；纯鉴权失败的 Key 在没有 Usage 数据的情况下永久 ERROR。
- **RR 索引在配置热加载时重置**: `KeyPoolManager.update_keys()` 总是将 `_index` 归零；
  大池下可能导致"新 Key 集中被用"。这是设计选择（保证状态一致），如需加权调度见 PRD §5。

