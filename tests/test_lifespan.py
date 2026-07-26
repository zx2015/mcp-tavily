import asyncio
import sys
import os
import unittest

# 将项目根目录加入路径以方便导入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import TavilyAggregator
from app.core.key import Key


class TestLifespanRegistration(unittest.IsolatedAsyncioTestCase):
    """回归测试：确保 UsageMonitor 后台任务真正被 FastMCP 启动。

    历史 Bug：TavilyAggregator 曾用 `@self.lifespan()` 装饰器"注册"自定义生命周期，
    但当前 fastmcp 版本中 `FastMCP.lifespan` 是一个普通的 @asynccontextmanager 实例方法
    （用于 `async with server.lifespan():` 汇总所有 Provider 的生命周期），不是装饰器工厂。
    用它装饰函数不会报错（因为 contextlib 生成的上下文管理器对象本身可调用），但从未把
    自定义的 aggregator_lifespan 真正设置为 server._lifespan——`monitor_usage_task` 这个
    后台任务因此从未启动过，且没有任何异常或错误日志，只能通过实际运行观察"该有的日志
    完全不出现"才能发现。PRD §2.1 要求的主动配额监控/主动熔断功能因此完全没有生效。
    """

    async def test_lifespan_is_not_the_fastmcp_default(self):
        """server._lifespan 不应停留在 fastmcp 内置的 default_lifespan"""
        server = TavilyAggregator()
        self.assertNotEqual(
            getattr(server._lifespan, "__name__", None),
            "default_lifespan",
            "server._lifespan 仍是 fastmcp 默认值，说明自定义生命周期未被注册",
        )

    async def test_monitor_usage_task_actually_starts_during_lifespan(self):
        """进入 server 的生命周期上下文后，UsageMonitor 后台任务应该真正在运行"""
        server = TavilyAggregator()
        server.key_manager.update_keys([Key("test-key-1")])

        async with server._lifespan_manager():
            await asyncio.sleep(0.05)
            self.assertIsNotNone(server._monitor_task, "monitor_usage_task 未被创建")
            self.assertFalse(
                server._monitor_task.done(), "monitor_usage_task 在生命周期内不应提前结束"
            )

    async def test_monitor_usage_task_is_cancelled_on_shutdown(self):
        """退出生命周期上下文后，后台任务应被优雅取消，不应残留悬挂任务"""
        server = TavilyAggregator()
        # 使用空 Key 池，让 monitor_usage_task 走"无 Key，sleep(60)"分支，避免测试
        # 触发真实网络请求（httpx 的异步清理需要额外事件循环轮次，会让断言产生偶发抖动）。
        server.key_manager.update_keys([])

        async with server._lifespan_manager():
            await asyncio.sleep(0.05)
            task = server._monitor_task

        # 生命周期管理器的 finally 块内部已 `await task`，退出 async with 时应已完成取消
        self.assertTrue(task.done(), "monitor_usage_task 在生命周期结束后仍未被取消/完成")
        self.assertTrue(task.cancelled(), "monitor_usage_task 应以 CancelledError 结束，而非正常返回")


if __name__ == "__main__":
    unittest.main()
