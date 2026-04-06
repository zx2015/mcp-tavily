import asyncio
import os
import sys
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

# 初始化日志
logger = setup_logger()

# 初始化 FastMCP
mcp = FastMCP("mcp-tavily")

# 初始化配置与 Key 池
config_manager = ConfigManager()
key_manager = KeyPoolManager(config_manager.keys)

# 注册配置热加载回调
config_manager.register_callback(key_manager.update_keys)
config_manager.start_watching()

@mcp.lifespan()  # type: ignore
@asynccontextmanager
async def lifespan(mcp_instance: FastMCP):
    """管理 FastMCP 生命周期，启动后台监控任务"""
    logger.info("Initializing background tasks...")
    # 启动异步监控任务
    task = asyncio.create_task(monitor_usage_task(lambda: key_manager.all_keys))
    
    try:
        yield
    finally:
        logger.info("Shutting down background tasks...")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

# --- 工具实现 ---

@mcp.tool(name="tavily-search", description=TAVILY_SEARCH_DESCRIPTION)
async def tavily_search(
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
    """执行网页搜索"""
    async def _call(api_key: str):
        client = TavilyClient(api_key=api_key)
        kwargs = {
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "days": days,
            "max_results": max_results,
            "include_images": include_images,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
            "include_image_descriptions": include_image_descriptions
        }
        return client.search(**{k: v for k, v in kwargs.items() if v is not None})

    return await key_manager.execute_with_retry(_call)


@mcp.tool(name="tavily-extract", description=TAVILY_EXTRACT_DESCRIPTION)
async def tavily_extract(
    urls: List[str],
    extract_depth: Optional[str] = "basic",
    include_images: Optional[bool] = False
) -> Any:
    """提取网页内容"""
    async def _call(api_key: str):
        client = TavilyClient(api_key=api_key)
        return client.extract(
            urls=urls,
            extract_depth=extract_depth,
            include_images=include_images
        )

    return await key_manager.execute_with_retry(_call)


@mcp.tool(name="tavily-crawl", description=TAVILY_CRAWL_DESCRIPTION)
async def tavily_crawl(
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
            "url": url,
            "max_depth": max_depth,
            "max_breadth": max_breadth,
            "limit": limit,
            "instructions": instructions,
            "select_paths": select_paths,
            "exclude_paths": exclude_paths,
            "include_images": include_images,
            "allow_external": allow_external
        }
        return client.crawl(**{k: v for k, v in kwargs.items() if v is not None})

    return await key_manager.execute_with_retry(_call)


@mcp.tool(name="tavily-map", description=TAVILY_MAP_DESCRIPTION)
async def tavily_map(
    url: str,
    max_depth: Optional[int] = None,
    limit: Optional[int] = None,
    select_paths: Optional[List[str]] = None
) -> Any:
    """生成网站地图"""
    async def _call(api_key: str):
        client = TavilyClient(api_key=api_key)
        kwargs = {
            "url": url,
            "max_depth": max_depth,
            "limit": limit,
            "select_paths": select_paths
        }
        return client.map(**{k: v for k, v in kwargs.items() if v is not None})

    return await key_manager.execute_with_retry(_call)


if __name__ == "__main__":
    if not key_manager.all_keys:
        logger.error("No Tavily API keys configured. Please set TAVILY_API_KEYS in .env or environment.")
        sys.exit(1)
        
    logger.info("Starting mcp-tavily service...")
    mcp.run()
