import asyncio
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# 将项目根目录加入路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import TavilyAggregator
from app.core.key import Key, KeyStatus

class TestMCPIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        """测试前准备：初始化 TavilyAggregator 实例并 Mock Key 池"""
        self.server = TavilyAggregator()
        self.test_keys = [Key("test-key-1"), Key("test-key-2")]
        self.server.key_manager.update_keys(self.test_keys)
        # 重置索引
        self.server.key_manager._index = 0

    @patch("app.main.TavilyClient")
    async def test_tavily_search_success(self, MockClient):
        """验证成功调用 tavily-search 工具"""
        mock_instance = MockClient.return_value
        mock_instance.search.return_value = {"results": [{"title": "Test Result", "url": "http://test.com"}]}

        # 直接调用实例方法
        result = await self.server.tavily_search(query="hello")

        # 断言
        self.assertIn("results", result)
        self.assertEqual(result["results"][0]["title"], "Test Result")
        MockClient.assert_called_with(api_key="test-key-1")

    @patch("app.main.TavilyClient")
    async def test_round_robin_and_retry_on_429(self, MockClient):
        """验证 429 报错时的自动切换和重试逻辑"""
        mock_instance = MockClient.return_value
        
        # 模拟第一次调用抛出 429 错误，第二次调用成功
        mock_instance.search.side_effect = [
            Exception("HTTP 429: Rate Limit Exceeded"),
            {"results": [{"title": "Success after retry"}]}
        ]

        result = await self.server.tavily_search(query="retry test")

        # 断言结果成功
        self.assertEqual(result["results"][0]["title"], "Success after retry")
        
        # 验证切换了 Key
        self.assertEqual(MockClient.call_args_list[0][1]["api_key"], "test-key-1")
        self.assertEqual(MockClient.call_args_list[1][1]["api_key"], "test-key-2")
        self.assertEqual(self.test_keys[0].status, KeyStatus.COOLDOWN)

    async def test_mcp_tools_registration(self):
        """验证所有官方工具是否已成功注册到 FastMCP"""
        # 异步调用 _list_tools() (继承自父类)
        tools = await self.server._list_tools()
        tool_names = [t.name for t in tools]

        expected_tools = ["tavily-search", "tavily-extract", "tavily-crawl", "tavily-map"]
        for name in expected_tools:
            self.assertIn(name, tool_names)

    @patch("app.main.TavilyClient")
    async def test_401_failure_logs_position_and_tail(self, MockClient):
        """回归测试：401 鉴权失败时，日志应包含"第 N 个 Key"与"尾号 xxxxxx"，便于用户定位"""
        # 给 Key 打上 position（与 ConfigManager 实际行为一致）
        self.test_keys[0].position = 1
        self.test_keys[1].position = 2
        # raw_key 末 6 位 = "ey1234"
        self.test_keys[0].raw_key = "tvly-fake-key-ey1234"

        mock_instance = MockClient.return_value
        mock_instance.search.side_effect = Exception("HTTP 401: Unauthorized")

        with self.assertLogs("app.core.manager", level="ERROR") as cm:
            with self.assertRaises(Exception):
                await self.server.tavily_search(query="will fail")

        # 验证日志含位置 + 末 6 位
        joined = "\n".join(cm.output)
        self.assertIn("[Key失效]", joined)
        self.assertIn("第 1 个 Key", joined)
        self.assertIn("尾号 ey1234", joined)
        self.assertEqual(self.test_keys[0].status, KeyStatus.ERROR)

    @patch("app.main.TavilyClient")
    async def test_429_cooldown_logs_position_and_tail(self, MockClient):
        """回归测试：429 限流时，日志应包含"第 N 个 Key"与"尾号 xxxxxx"（WARNING 级）"""
        self.test_keys[0].position = 1
        self.test_keys[1].position = 2
        self.test_keys[0].raw_key = "tvly-fake-key-cooldn"

        mock_instance = MockClient.return_value
        mock_instance.search.side_effect = [
            Exception("HTTP 429: Rate Limit Exceeded"),
            {"results": [{"title": "fallback success"}]},
        ]

        with self.assertLogs("app.core.manager", level="WARNING") as cm:
            result = await self.server.tavily_search(query="retry test")

        joined = "\n".join(cm.output)
        self.assertIn("[Key限流]", joined)
        self.assertIn("第 1 个 Key", joined)
        self.assertIn("尾号 cooldn", joined)  # 末 6 位
        self.assertEqual(result["results"][0]["title"], "fallback success")
        self.assertEqual(self.test_keys[0].status, KeyStatus.COOLDOWN)

if __name__ == "__main__":
    unittest.main()
