import unittest
from unittest.mock import patch
import sys
import os

# 将项目根目录加入路径以方便导入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import TavilyAggregator
from app.core.key import Key


class TestTransportConfiguration(unittest.TestCase):
    """验证服务仅通过 Streamable HTTP 对外提供 MCP 接口（不使用 stdio / SSE）"""

    def setUp(self):
        self.server = TavilyAggregator()
        self.server.key_manager.update_keys([Key("test-key-1")])

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(TavilyAggregator, "run")
    def test_start_uses_streamable_http_with_defaults(self, mock_run):
        """未设置环境变量时，应使用默认 host/port/path 启动 Streamable HTTP"""
        self.server.start()

        mock_run.assert_called_once_with(
            transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp"
        )

    @patch.dict(
        os.environ,
        {"MCP_HOST": "127.0.0.1", "PORT": "9999", "MCP_PATH": "/custom-mcp"},
        clear=True,
    )
    @patch.object(TavilyAggregator, "run")
    def test_start_respects_env_overrides(self, mock_run):
        """应支持通过 MCP_HOST/PORT/MCP_PATH 覆盖默认监听配置"""
        self.server.start()

        mock_run.assert_called_once_with(
            transport="streamable-http", host="127.0.0.1", port=9999, path="/custom-mcp"
        )

    @patch.object(TavilyAggregator, "run")
    def test_start_never_uses_stdio_or_sse(self, mock_run):
        """回归测试：确保任何情况下都不会以 stdio 或 sse 传输启动"""
        self.server.start()

        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["transport"], "streamable-http")
        self.assertNotIn(kwargs["transport"], ("stdio", "sse"))

    @patch.object(TavilyAggregator, "run")
    def test_start_exits_when_no_keys_configured(self, mock_run):
        """没有可用 Key 时应直接退出，不启动 HTTP 服务"""
        self.server.key_manager.update_keys([])

        with self.assertRaises(SystemExit):
            self.server.start()

        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
