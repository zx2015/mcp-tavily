import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
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

    @patch("app.core.manager.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.main.TavilyClient")
    async def test_dns_failure_retries_in_place_without_burning_key_budget(self, MockClient, mock_sleep):
        """回归测试：DNS 解析失败（如 api.tavily.com 无法解析）应在同一个 Key 上快速重试自愈，
        而不是像 429/401 一样直接切换/惩罚 Key。复现的是实际生产环境中 OpenCode 调用时遇到的
        `NameResolutionError: Failed to resolve 'api.tavily.com'` 故障。
        """
        dns_error = Exception(
            "HTTPSConnectionPool(host='api.tavily.com', port=443): Max retries exceeded "
            "with url: /search (Caused by NameResolutionError(\"Failed to resolve "
            "'api.tavily.com' ([Errno -3] Temporary failure in name resolution)\"))"
        )
        mock_instance = MockClient.return_value
        # 第一次 DNS 失败，快速重试一次后成功——全程应只用第一个 Key，不应轮换到第二个 Key
        mock_instance.search.side_effect = [dns_error, {"results": [{"title": "recovered"}]}]

        result = await self.server.tavily_search(query="dns blip")

        self.assertEqual(result["results"][0]["title"], "recovered")
        # 两次调用都应使用同一个 Key（test-key-1），证明网络错误走的是原地重试而非 Key 轮换
        self.assertEqual(MockClient.call_args_list[0][1]["api_key"], "test-key-1")
        self.assertEqual(MockClient.call_args_list[1][1]["api_key"], "test-key-1")
        # DNS 错误不应影响 Key 的状态（既不冷却也不标记为 ERROR）
        self.assertEqual(self.test_keys[0].status, KeyStatus.ACTIVE)

    @patch("app.core.manager.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.main.TavilyClient")
    async def test_dns_failure_falls_through_to_next_key_after_exhausting_quick_retries(
        self, MockClient, mock_sleep
    ):
        """回归测试：若 DNS 故障持续超过快速重试预算（NETWORK_ERROR_MAX_RETRIES 次），
        应最终转去尝试池中下一个 Key（而不是无限重试同一个 Key）。"""
        dns_error = Exception(
            "NameResolutionError: Failed to resolve 'api.tavily.com' "
            "([Errno -5] No address associated with hostname)"
        )
        mock_instance = MockClient.return_value
        # 第一个 Key 上：初始尝试 + 2 次快速重试均失败 = 3 次；随后轮换到第二个 Key 并成功
        mock_instance.search.side_effect = [
            dns_error, dns_error, dns_error,
            {"results": [{"title": "success on second key"}]},
        ]

        result = await self.server.tavily_search(query="prolonged dns outage")

        self.assertEqual(result["results"][0]["title"], "success on second key")
        api_keys_used = [call[1]["api_key"] for call in MockClient.call_args_list]
        self.assertEqual(api_keys_used, ["test-key-1", "test-key-1", "test-key-1", "test-key-2"])
        # 网络错误不应把 Key 标记为 COOLDOWN/ERROR
        self.assertEqual(self.test_keys[0].status, KeyStatus.ACTIVE)

    @patch("app.main.TavilyClient")
    async def test_tavily_search_runs_blocking_call_in_thread(self, MockClient):
        """回归测试：TavilyClient 的同步阻塞调用应通过 asyncio.to_thread 放入线程池执行，
        不应占用事件循环——否则一次搜索请求耗时期间，其他并发的 MCP 请求会被整体阻塞。"""
        import time

        def blocking_search(**kwargs):
            time.sleep(0.3)  # 模拟真实网络请求的阻塞耗时
            return {"results": [{"title": "slow but non-blocking"}]}

        mock_instance = MockClient.return_value
        mock_instance.search.side_effect = blocking_search

        tick_count = 0

        async def tick_counter():
            nonlocal tick_count
            # 若事件循环被阻塞，本协程在 search 执行期间不会被调度
            for _ in range(6):
                await asyncio.sleep(0.05)
                tick_count += 1

        search_task = asyncio.create_task(self.server.tavily_search(query="slow"))
        ticker_task = asyncio.create_task(tick_counter())
        result, _ = await asyncio.gather(search_task, ticker_task)

        self.assertEqual(result["results"][0]["title"], "slow but non-blocking")
        # 事件循环未被阻塞的情况下，0.3s 的阻塞期间 tick_counter 应已被调度多次
        self.assertGreaterEqual(tick_count, 3)

if __name__ == "__main__":
    unittest.main()
