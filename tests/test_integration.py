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

if __name__ == "__main__":
    unittest.main()
