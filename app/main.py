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
        super().__init__("mcp-tavily")
        self.config_manager = ConfigManager()
        self.key_manager = KeyPoolManager(self.config_manager.keys)
        self.config_manager.register_callback(self.key_manager.update_keys)
        self.config_manager.start_watching()
        self._register_lifespan()
        self._register_tools()

    def _register_lifespan(self):
        @self.lifespan()  # type: ignore
        @asynccontextmanager
        async def aggregator_lifespan(mcp_instance: FastMCP):
            logger.info("Initializing background tasks...")
            task = asyncio.create_task(monitor_usage_task(lambda: self.key_manager.all_keys))
            try:
                yield
            finally:
                logger.info("Shutting down background tasks...")
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass

    def _register_tools(self):
        self.tool(name="tavily-search", description=TAVILY_SEARCH_DESCRIPTION)(self.tavily_search)
        self.tool(name="tavily-extract", description=TAVILY_EXTRACT_DESCRIPTION)(self.tavily_extract)
        self.tool(name="tavily-crawl", description=TAVILY_CRAWL_DESCRIPTION)(self.tavily_crawl)
        self.tool(name="tavily-map", description=TAVILY_MAP_DESCRIPTION)(self.tavily_map)

    async def tavily_search(self, query: str, search_depth: str = "basic", topic: str = "general", days: Optional[int] = None, max_results: int = 5, include_images: bool = False, include_answer: bool = False, include_raw_content: bool = False, include_domains: Optional[List[str]] = None, exclude_domains: Optional[List[str]] = None, time_range: Optional[str] = None, include_image_descriptions: bool = False) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {"query": query, "search_depth": search_depth, "topic": topic, "days": days, "max_results": max_results, "include_images": include_images, "include_answer": include_answer, "include_raw_content": include_raw_content, "include_domains": include_domains, "exclude_domains": exclude_domains, "include_image_descriptions": include_image_descriptions}
            return client.search(**{k: v for k, v in kwargs.items() if v is not None})
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_extract(self, urls: List[str], extract_depth: str = "basic", include_images: bool = False) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            return client.extract(urls=urls, extract_depth=extract_depth, include_images=include_images)
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_crawl(self, url: str, max_depth: Optional[int] = None, max_breadth: Optional[int] = None, limit: Optional[int] = None, instructions: Optional[str] = None, select_paths: Optional[List[str]] = None, exclude_paths: Optional[List[str]] = None, include_images: bool = False, allow_external: bool = False) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {"url": url, "max_depth": max_depth, "max_breadth": max_breadth, "limit": limit, "instructions": instructions, "select_paths": select_paths, "exclude_paths": exclude_paths, "include_images": include_images, "allow_external": allow_external}
            return client.crawl(**{k: v for k, v in kwargs.items() if v is not None})
        return await self.key_manager.execute_with_retry(_call)

    async def tavily_map(self, url: str, max_depth: Optional[int] = None, limit: Optional[int] = None, select_paths: Optional[List[str]] = None) -> Any:
        async def _call(api_key: str):
            client = TavilyClient(api_key=api_key)
            kwargs = {"url": url, "max_depth": max_depth, "limit": limit, "select_paths": select_paths}
            return client.map(**{k: v for k, v in kwargs.items() if v is not None})
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
