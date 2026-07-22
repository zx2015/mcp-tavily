import logging
import sys
import os
import unittest

# 将项目根目录加入路径以方便导入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 触发 app.main 的模块级 setup_logger() 调用（若尚未被其他测试文件触发过）
import app.main  # noqa: F401
from app.utils.logger import setup_logger


class _ListHandler(logging.Handler):
    """用于在测试中捕获日志记录，而不依赖真实文件"""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestLoggingPropagation(unittest.TestCase):
    """回归测试：确保 app.core / app.tasks 等模块的日志不会被静默丢弃"""

    def setUp(self):
        self.root_logger = logging.getLogger()
        self.capture_handler = _ListHandler()
        self.root_logger.addHandler(self.capture_handler)

    def tearDown(self):
        self.root_logger.removeHandler(self.capture_handler)

    def test_setup_logger_attaches_handlers_to_root_logger(self):
        """setup_logger 应当把 Handler 挂在根 Logger 上，而不仅仅是具名 Logger"""
        setup_logger()
        handler_types = [type(h).__name__ for h in self.root_logger.handlers]
        self.assertIn("RotatingFileHandler", handler_types)
        self.assertIn("StreamHandler", handler_types)

    def test_config_manager_logs_propagate_to_root_handlers(self):
        """ConfigManager 的日志应能被根 Logger 的 Handler 捕获（此前会被静默丢弃）"""
        from app.core.config import logger as config_logger

        config_logger.info("TEST_MARKER config manager log")

        messages = [r.getMessage() for r in self.capture_handler.records]
        self.assertTrue(any("TEST_MARKER config manager log" in m for m in messages))

    def test_key_pool_manager_logs_propagate_to_root_handlers(self):
        """KeyPoolManager 的日志（如冷却、切换 Key）应能被根 Logger 的 Handler 捕获"""
        from app.core.manager import logger as manager_logger

        manager_logger.warning("TEST_MARKER key pool warning")

        messages = [r.getMessage() for r in self.capture_handler.records]
        self.assertTrue(any("TEST_MARKER key pool warning" in m for m in messages))

    def test_usage_monitor_logs_propagate_to_root_handlers(self):
        """UsageMonitor 的日志（如配额同步）应能被根 Logger 的 Handler 捕获"""
        from app.tasks.monitor import logger as monitor_logger

        monitor_logger.info("TEST_MARKER usage monitor synced")

        messages = [r.getMessage() for r in self.capture_handler.records]
        self.assertTrue(any("TEST_MARKER usage monitor synced" in m for m in messages))

    def test_root_logger_level_respects_log_level_env(self):
        """根 Logger 级别应遵循 LOG_LEVEL 环境变量（默认为 INFO）而非静默 WARNING"""
        setup_logger()
        # 默认（未设置 LOG_LEVEL 或为 INFO）情况下应可捕获 INFO 级别日志
        self.assertLessEqual(self.root_logger.getEffectiveLevel(), logging.INFO)


if __name__ == "__main__":
    unittest.main()
