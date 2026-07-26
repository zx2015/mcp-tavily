import asyncio
import httpx
import logging
from typing import List, Callable
from app.core.key import Key, KeyStatus

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
                key_info = data.get("key") or {}
                account_info = data.get("account") or {}

                usage = key_info.get("usage")
                if usage is None:
                    usage = 0

                # Tavily /usage 接口对"无限额度"的 Key 会返回 `"limit": null`（而非缺省该字段），
                # dict.get(key, default) 只在字段缺失时才用 default，字段存在但值为 None 时仍
                # 返回 None——因此必须显式判断 None，否则 limit 会一路是 None 传入
                # Key.update_usage()，触发 `usage >= limit > 0` 的 TypeError（int 与 None 比较）。
                limit = key_info.get("limit")
                if limit is None or limit == 0:
                    # key 级别未设置限制（或显式为 0），尝试使用 account 级别的 plan_limit
                    limit = account_info.get("plan_limit")
                    if limit is None:
                        limit = 0

                # 在 update_usage 之前记录旧状态，以便检测"刚发生的 EXHAUSTED 转换"
                previous_status = key.status
                key.update_usage(usage, limit)
                logger.info(f"Key {key.label} usage synced: {usage}/{limit}")

                # 主动熔断事件：配额耗尽（PRD §2.1）。仅在状态由非 EXHAUSTED 变为 EXHAUSTED
                # 时打一次日志，避免每轮轮询都重复刷。
                if (
                    usage >= limit > 0
                    and previous_status != KeyStatus.EXHAUSTED
                    and key.status == KeyStatus.EXHAUSTED
                ):
                    logger.error(
                        f"[Key失效] 第 {key.position} 个 Key（尾号 {key.tail}）配额耗尽 "
                        f"({usage}/{limit})，已标记为 EXHAUSTED"
                    )
            elif response.status_code == 401:
                logger.error(
                    f"[Key失效] 第 {key.position} 个 Key（尾号 {key.tail}）"
                    f"使用情况查询返回 401（鉴权失败）。原始错误: Invalid API Key"
                )
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
