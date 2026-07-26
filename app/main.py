import asyncio
import os
import sys
import logging
from typing import List, Optional, Any
from contextlib import asynccontextmanager
from fastmcp import FastMCP
from tavily import TavilyClient

from app.core.key import Key
from app.core.config import ConfigManager
from app.core.manager import KeyPoolManager
from app.utils.logger import setup_logger
from app.constants.tools import (
    TAVILY_SEARCH_DESCRIPTION, TAVILY_EXTRACT_DESCRIPTION,
    TAVILY_CRAWL_DESCRIPTION, TAVILY_MAP_DESCRIPTION
)
from app.tasks.monitor import monitor_usage_task

# 修正日志输出到 stderr
logger = setup_logger()

class TavilyAggregator(FastMCP):
    def __init__(self):
        # 注意：key_manager 必须在 super().__init__() 之前就绪，因为 lifespan 回调
        # （_aggregator_lifespan）需要引用它，而 FastMCP.__init__ 只在构造时通过
        # `lifespan=` 关键字参数接收生命周期回调——事后再用 `@self.lifespan()`
        # 装饰是无效的：FastMCP.lifespan 在当前版本中是一个普通的 @asynccontextmanager
        # 实例方法（用于 `async with server.lifespan():` 汇总多个 Provider 的生命周期），
        # 不是装饰器工厂。历史版本正是这样误用的：`@self.lifespan()` 悄悄返回一个可调用的
        # 上下文管理器对象，把它当装饰器用不会报错，但也从未把 aggregator_lifespan 真正注册为
        # server._lifespan（一直保持 fastmcp 内置的 default_lifespan），导致
        # monitor_usage_task 这个后台任务从未被启动过——PRD §2.1 要求的"主动配额监控/主动熔断"
        # 因此完全没有生效，且没有任何报错或日志（已通过单测复现并修复，见
        # tests/test_lifespan.py）。
        self.config_manager = ConfigManager()
        self.key_manager = KeyPoolManager(self.config_manager.keys)
        self.config_manager.register_callback(self.key_manager.update_keys)
        self.config_manager.start_watching()
        super().__init__("mcp-tavily", lifespan=self._aggregator_lifespan)
        self._register_tools()

    @asynccontextmanager
    async def _aggregator_lifespan(self, mcp_instance: "TavilyAggregator"):
        """服务生命周期回调：启动/关闭 UsageMonitor 后台任务。

        必须通过 FastMCP 构造函数的 `lifespan=` 参数传入（见 __init__），而不是
        事后用装饰器"注册"——后者在当前 fastmcp 版本下是无效操作。
        """
        logger.info("Initializing background tasks...")
        task = asyncio.create_task(monitor_usage_task(lambda: self.key_manager.all_keys))
        # 暴露为实例属性，便于测试直接断言该任务的运行/取消状态，而不必依赖脆弱的
        # asyncio.all_tasks() 全量扫描（同一进程内其他并发任务可能造成断言抖动）。
        self._monitor_task = task
        try:
            yield
        finally:
            logger.info("Shutting down background tasks...")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _register_tools(self):
        self.tool(name="tavily-search", description=TAVILY_SEARCH_DESCRIPTION)(self.tavily_search)
        self.tool(name="tavily-extract", description=TAVILY_EXTRACT_DESCRIPTION)(self.tavily_extract)
        self.tool(name="tavily-crawl", description=TAVILY_CRAWL_DESCRIPTION)(self.tavily_crawl)
        self.tool(name="tavily-map", description=TAVILY_MAP_DESCRIPTION)(self.tavily_map)

    async def tavily_search(self, query: str, search_depth: str = "basic", topic: str = "general", days: Optional[int] = None, max_results: int = 5, include_images: bool = False, include_answer: bool = False, include_raw_content: bool = False, include_domains: Optional[List[str]] = None, exclude_domains: Optional[List[str]] = None, time_range: Optional[str] = None, include_image_descriptions: bool = False) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {"query": query, "search_depth": search_depth, "topic": topic, "days": days, "max_results": max_results, "include_images": include_images, "include_answer": include_answer, "include_raw_content": include_raw_content, "include_domains": include_domains, "exclude_domains": exclude_domains, "include_image_descriptions": include_image_descriptions}
            # tavily-python 的 TavilyClient 底层用 requests（同步阻塞 I/O）。若直接在
            # async 函数里调用，会整个占用 asyncio 事件循环，导致该请求等待网络响应期间
            # （包括 DNS 解析、连接、超时重试等）所有其他并发的 MCP 请求全部被阻塞。
            # 用 asyncio.to_thread 把阻塞调用放到线程池执行，事件循环可继续处理其他请求。
            return await asyncio.to_thread(client.search, **{k: v for k, v in kwargs.items() if v is not None})
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_extract(self, urls: List[str], extract_depth: str = "basic", include_images: bool = False) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            return await asyncio.to_thread(client.extract, urls=urls, extract_depth=extract_depth, include_images=include_images)
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_crawl(self, url: str, max_depth: Optional[int] = None, max_breadth: Optional[int] = None, limit: Optional[int] = None, instructions: Optional[str] = None, select_paths: Optional[List[str]] = None, exclude_paths: Optional[List[str]] = None, include_images: bool = False, allow_external: bool = False) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {"url": url, "max_depth": max_depth, "max_breadth": max_breadth, "limit": limit, "instructions": instructions, "select_paths": select_paths, "exclude_paths": exclude_paths, "include_images": include_images, "allow_external": allow_external}
            return await asyncio.to_thread(client.crawl, **{k: v for k, v in kwargs.items() if v is not None})
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_map(self, url: str, max_depth: Optional[int] = None, limit: Optional[int] = None, select_paths: Optional[List[str]] = None) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {"url": url, "max_depth": max_depth, "limit": limit, "select_paths": select_paths}
            return await asyncio.to_thread(client.map, **{k: v for k, v in kwargs.items() if v is not None})
        return await self.key_manager.execute_with_retry(_call)

    def start(self):
        """启动服务器（仅支持 Streamable HTTP 传输）"""
        if not self.key_manager.all_keys:
            logger.error("No Tavily API keys configured. Service exiting.")
            sys.exit(1)

        host = os.getenv("MCP_HOST", "0.0.0.0")
        port = int(os.getenv("PORT", 8000))
        path = os.getenv("MCP_PATH", "/mcp")

        logger.info(f"Starting Streamable HTTP server on http://{host}:{port}{path} ...")
        self.run(transport="streamable-http", host=host, port=port, path=path)

if __name__ == "__main__":
    server = TavilyAggregator()
    server.start()
