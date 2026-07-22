import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# 标记属性，用于判断根 Logger 是否已完成过 Handler 配置，避免重复添加
_ROOT_CONFIGURED_ATTR = "_mcp_tavily_configured"


def setup_logger(name: str = "mcp_tavily", log_file: str = "app.log", level: int | None = None):
    """配置日志系统。

    关键点：Handler（滚动文件 + stderr）挂载在**根 Logger**上，而不是仅挂在
    `name` 对应的 Logger 上。这是因为 `app.core.config` / `app.core.manager` /
    `app.tasks.monitor` 等模块都使用 `logging.getLogger(__name__)` 获取的是与
    `name`（默认 "mcp_tavily"）互不相关的独立 Logger；如果只给 `name` 这个
    Logger 挂 Handler，其余模块的日志（Key 池调度、冷却、配额同步、热加载等
    关键运行时事件）会因为找不到匹配的 Handler 而被静默丢弃，无法写入
    `app.log` 也不会出现在容器日志中。

    通过把 Handler 挂在根 Logger 上，并保持子 Logger 的 `propagate=True`
    （Python 默认行为），所有 `app.*` 模块的日志都会沿 Logger 层级向上传播到
    根 Logger 并被同一套 Handler 处理，从而保证滚动日志文件真实反映系统运行
    状态。

    日志级别可通过 `LOG_LEVEL` 环境变量控制（INFO/DEBUG/WARNING/ERROR），
    默认为 INFO。
    """
    if level is None:
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 防止重复添加 Handler（例如测试中多次调用 setup_logger）
    if not getattr(root_logger, _ROOT_CONFIGURED_ATTR, False):
        # 轮转文件 Handler: 每个文件最大 5MB，保留 5 个备份
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_format)

        # 关键修复：将控制台日志输出到 stderr 而非 stdout
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(file_format)

        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        setattr(root_logger, _ROOT_CONFIGURED_ATTR, True)

    # 返回具名 Logger 供调用方（如 app/main.py）直接使用；其日志会传播到根 Logger
    return logging.getLogger(name)
