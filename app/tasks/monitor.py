import asyncio
import httpx
import logging
from typing import List, Callable
from app.core.key import Key

logger = logging.getLogger(__name__)

USAGE_URL = "https://api.tavily.com/usage"

async def check_key_usage(key: Key):
    """查询单个 Key 的使用情况并更新状态"""
    headers = {"Authorization": f"Bearer {key.raw_key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(USAGE_URL, headers=headers)
            if response.status_code == 200:
                data = response.json()
                usage = data.get("key", {}).get("usage", 0)
                limit = data.get("key", {}).get("limit", 0)
                
                # 如果没有设置 key limit，则尝试使用 account plan_limit
                if limit == 0:
                    limit = data.get("account", {}).get("plan_limit", 0)
                
                key.update_usage(usage, limit)
                logger.info(f"Key {key.label} usage synced: {usage}/{limit}")
            elif response.status_code == 401:
                logger.error(f"Key {key.label} usage check failed: Invalid API Key (401)")
            else:
                logger.warning(f"Key {key.label} usage check failed with status {response.status_code}")
    except Exception as e:
        logger.error(f"Error checking usage for Key {key.label}: {e}")

async def monitor_usage_task(keys_provider: Callable[[], List[Key]], interval_minutes: int = 10):
    """定期同步所有 Key 使用情况的后台任务"""
    logger.info(f"Usage monitor task started. Interval: {interval_minutes}min")
    while True:
        keys: List[Key] = keys_provider()
        if not keys:
            await asyncio.sleep(60)
            continue
            
        tasks = [check_key_usage(key) for key in keys]
        await asyncio.gather(*tasks)
        
        await asyncio.sleep(interval_minutes * 60)
