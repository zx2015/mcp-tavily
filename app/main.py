import asyncio
import os
import sys
from typing import List, Optional, Any, Callable
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

logger = setup_logger()

class TavilyAggregator(FastMCP):
    """
    Tavily MCP 聚合服务器类。
    继承自 FastMCP，集成多 Key 轮询、自动重试和配额监控功能。
    """
    def __init__(self):
        # 初始化父类 FastMCP
        super().__init__("mcp-tavily")
        
        # 初始化配置与 Key 池管理器
        self.config_manager = ConfigManager()
        self.key_manager = KeyPoolManager(self.config_manager.keys)
        
        # 注册配置热加载回调
        self.config_manager.register_callback(self.key_manager.update_keys)
        self.config_manager.start_watching()
        
        # 注册生命周期钩子
        self._register_lifespan()
        
        # 注册工具
        self._register_tools()

    def _register_lifespan(self):
        """注册 FastMCP 生命周期管理"""
        @self.lifespan()  # type: ignore
        @asynccontextmanager
        async def aggregator_lifespan(mcp_instance: FastMCP):
            logger.info("Initializing background tasks in TavilyAggregator...")
            task = asyncio.create_task(
                monitor_usage_task(lambda: self.key_manager.all_keys)
            )
            try:
                yield
            finally:
                logger.info("Shutting down TavilyAggregator background tasks...")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def _register_tools(self):
        """注册 MCP 工具"""
        # 在类内部使用装饰器语法手动包装方法并添加到 self.tools
        self.tool(name="tavily-search", description=TAVILY_SEARCH_DESCRIPTION)(self.tavily_search)
        self.tool(name="tavily-extract", description=TAVILY_EXTRACT_DESCRIPTION)(self.tavily_extract)
        self.tool(name="tavily-crawl", description=TAVILY_CRAWL_DESCRIPTION)(self.tavily_crawl)
        self.tool(name="tavily-map", description=TAVILY_MAP_DESCRIPTION)(self.tavily_map)

    # --- 工具实现方法 ---

    async def tavily_search(
        self,
        query: str,
        search_depth: Optional[str] = "basic",
        topic: Optional[str] = "general",
        days: Optional[int] = None,
        max_results: Optional[int] = 5,
        include_images: Optional[bool] = False,
        include_answer: Optional[bool] = False,
        include_raw_content: Optional[bool] = False,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        include_image_descriptions: Optional[bool] = False
    ) -> Any:
        """执行网页搜索（支持多 Key 轮询）"""
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {
                "query": query, "search_depth": search_depth, "topic": topic, "days": days,
                "max_results": max_results, "include_images": include_images,
                "include_answer": include_answer, "include_raw_content": include_raw_content,
                "include_domains": include_domains, "exclude_domains": exclude_domains,
                "include_image_descriptions": include_image_descriptions
            }
            return client.search(**{k: v for k, v in kwargs.items() if v is not None})
        
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_extract(
        self, 
        urls: List[str], 
        extract_depth: Optional[str] = "basic", 
        include_images: Optional[bool] = False
    ) -> Any:
        """提取网页内容"""
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            return client.extract(urls=urls, extract_depth=extract_depth, include_images=include_images)
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_crawl(
        self, 
        url: str, 
        max_depth: Optional[int] = None, 
        max_breadth: Optional[int] = None, 
        limit: Optional[int] = None, 
        instructions: Optional[str] = None, 
        select_paths: Optional[List[str]] = None, 
        exclude_paths: Optional[List[str]] = None, 
        include_images: Optional[bool] = False, 
        allow_external: Optional[bool] = False
    ) -> Any:
        """深度爬取网站"""
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {
                "url": url, "max_depth": max_depth, "max_breadth": max_breadth, "limit": limit,
                "instructions": instructions, "select_paths": select_paths,
                "exclude_paths": exclude_paths, "include_images": include_images,
                "allow_external": allow_external
            }
            return client.crawl(**{k: v for k, v in kwargs.items() if v is not None})
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_map(
        self, 
        url: str, 
        max_depth: Optional[int] = None, 
        limit: Optional[int] = None, 
        select_paths: Optional[List[str]] = None
    ) -> Any:
        """生成网站地图"""
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {"url": url, "max_depth": max_depth, "limit": limit, "select_paths": select_paths}
            return client.map(**{k: v for k, v in kwargs.items() if v is not None})
        return await self.key_manager.execute_with_retry(_call)

    def start(self):
        """启动服务器"""
        if not self.key_manager.all_keys:
            logger.error("No Tavily API keys configured. Service exiting.")
            sys.exit(1)
            
        transport = os.getenv("MCP_TRANSPORT", "stdio")
        port = int(os.getenv("PORT", 8000))
        
        logger.info(f"TavilyAggregator starting with transport={transport} on port={port}...")
        
        if transport == "sse":
            self.run(transport="sse", host="0.0.0.0", port=port)
        else:
            self.run(transport="stdio")

if __name__ == "__main__":
    server = TavilyAggregator()
    server.start()
