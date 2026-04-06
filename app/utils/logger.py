import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(name: str = "mcp_tavily", log_file: str = "app.log", level=logging.INFO):
    """设置支持轮转的日志记录器"""
    
    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 防止重复添加 Handler
    if not logger.handlers:
        # 轮转文件 Handler: 每个文件最大 5MB，保留 5 个备份
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_format)

        # 控制台 Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(file_format)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
