import asyncio
import unittest
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# 将项目根目录加入路径以方便导入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.key import Key, KeyStatus
from app.tasks.monitor import check_key_usage, monitor_usage_task


def _mock_response(status_code: int, json_data=None):
    """构造一个假的 httpx.Response 对象"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


class TestCheckKeyUsage(unittest.IsolatedAsyncioTestCase):
    @patch("app.tasks.monitor.httpx.AsyncClient")
    async def test_sends_correct_bearer_authorization_header(self, MockAsyncClient):
        """回归测试：确保鉴权 Bug 不再复现——请求必须带上真实的 Key，而非占位符"""
        key = Key("tvly-real-secret-key")

        mock_client = MockAsyncClient.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(return_value=_mock_response(200, {"key": {"usage": 10, "limit": 100}}))

        await check_key_usage(key)

        # 校验实际发出的请求头中包含真实 Key，而不是硬编码的占位符
        _, call_kwargs = mock_client.get.call_args
        sent_headers = call_kwargs["headers"]
        self.assertIn("Authorization", sent_headers)
        auth_header = sent_headers["Authorization"]
        self.assertIn(key.raw_key, auth_header)
        self.assertTrue(auth_header.startswith("Bearer "))
        self.assertNotEqual(auth_header, "Bearer ******")

    @patch("app.tasks.monitor.httpx.AsyncClient")
    async def test_updates_key_usage_on_200(self, MockAsyncClient):
        """接口成功返回时，应正确解析 usage/limit 并更新 Key 状态"""
        key = Key("tvly-key-1")
        mock_client = MockAsyncClient.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(return_value=_mock_response(200, {"key": {"usage": 50, "limit": 100}}))

        await check_key_usage(key)

        self.assertEqual(key.usage, 50)
        self.assertEqual(key.limit, 100)
        self.assertEqual(key.status, KeyStatus.ACTIVE)

    @patch("app.tasks.monitor.httpx.AsyncClient")
    async def test_falls_back_to_account_plan_limit(self, MockAsyncClient):
        """当 key.limit 为 0 时，应回退使用 account.plan_limit"""
        key = Key("tvly-key-2")
        mock_client = MockAsyncClient.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(
            return_value=_mock_response(
                200, {"key": {"usage": 20, "limit": 0}, "account": {"plan_limit": 500}}
            )
        )

        await check_key_usage(key)

        self.assertEqual(key.usage, 20)
        self.assertEqual(key.limit, 500)

    @patch("app.tasks.monitor.httpx.AsyncClient")
    async def test_marks_exhausted_when_usage_reaches_limit(self, MockAsyncClient):
        """usage >= limit 时应主动熔断为 EXHAUSTED（PRD 2.1 主动熔断要求）"""
        key = Key("tvly-key-3")
        mock_client = MockAsyncClient.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(return_value=_mock_response(200, {"key": {"usage": 100, "limit": 100}}))

        await check_key_usage(key)

        self.assertEqual(key.status, KeyStatus.EXHAUSTED)

    @patch("app.tasks.monitor.httpx.AsyncClient")
    async def test_handles_401_without_raising(self, MockAsyncClient):
        """无效 Key 返回 401 时，不应抛出异常，也不应更新 usage"""
        key = Key("tvly-invalid-key")
        mock_client = MockAsyncClient.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(return_value=_mock_response(401))

        await check_key_usage(key)  # 不应抛出异常

        self.assertEqual(key.usage, 0)
        self.assertEqual(key.status, KeyStatus.ACTIVE)

    @patch("app.tasks.monitor.httpx.AsyncClient")
    async def test_handles_network_exception_without_raising(self, MockAsyncClient):
        """网络异常时应被捕获记录，不应向上抛出导致后台任务崩溃"""
        key = Key("tvly-key-4")
        mock_client = MockAsyncClient.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(side_effect=ConnectionError("boom"))

        await check_key_usage(key)  # 不应抛出异常


class TestMonitorUsageTask(unittest.IsolatedAsyncioTestCase):
    @patch("app.tasks.monitor.check_key_usage", new_callable=AsyncMock)
    async def test_polls_all_keys_and_sleeps_between_cycles(self, mock_check_key_usage):
        """验证后台任务会对每个 Key 调用一次 check_key_usage，并在两轮之间等待"""
        keys = [Key("tvly-a"), Key("tvly-b")]

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)
            # 第二次 sleep 后跳出循环，避免任务无限运行
            if len(sleep_calls) >= 1:
                raise asyncio.CancelledError()

        with patch("app.tasks.monitor.asyncio.sleep", side_effect=fake_sleep):
            with self.assertRaises(asyncio.CancelledError):
                await monitor_usage_task(lambda: keys, interval_minutes=1)

        self.assertEqual(mock_check_key_usage.await_count, len(keys))
        self.assertEqual(sleep_calls, [60])

    @patch("app.tasks.monitor.check_key_usage", new_callable=AsyncMock)
    async def test_skips_polling_when_no_keys(self, mock_check_key_usage):
        """当前没有可用 Key 时，应跳过本轮轮询并短暂等待，而不是报错"""
        call_count = 0

        async def fake_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch("app.tasks.monitor.asyncio.sleep", side_effect=fake_sleep):
            with self.assertRaises(asyncio.CancelledError):
                await monitor_usage_task(lambda: [], interval_minutes=1)

        mock_check_key_usage.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
