# Architecture Overview - mcp-tavily

| 版本号 | 日期       | 变更说明 | 作者       |
|--------|------------|----------|------------|
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

### 3.4 UsageMonitor (后台任务)
- **实现:** `asyncio.create_task` 启动永久循环任务。
- **逻辑:** 定期 (10min) 调用 `/usage` API 同步状态。

## 4. 数据流 (Data Flow)
(数据流说明保持不变)

## 5. 设计约束与安全 (Constraints & Security)
- **敏感信息:** 日志严禁打印完整 Key，仅显示脱敏版本 (`tvly-abcd...wxyz`)。
- **热加载响应:** 动态调整 Key 池时应保证当前正在执行的请求不受影响。

## 6. 异常处理策略 (Error Handling)
(策略表保持不变)
