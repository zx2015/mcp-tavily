import asyncio
import logging
from typing import List, Optional, Callable, Any
from app.core.key import Key, KeyStatus

logger = logging.getLogger(__name__)


class KeyPoolManager:
    def __init__(self, initial_keys: List[Key]):
        self._keys = initial_keys
        self._index = 0
        self._lock = asyncio.Lock()

    def update_keys(self, new_keys: List[Key]):
        """供 ConfigManager 回调使用，用于更新 Key 池"""
        # 注意：这里我们简单替换列表并重置索引，以确保状态一致性
        self._keys = new_keys
        self._index = 0
        logger.info(f"KeyPoolManager updated with {len(new_keys)} keys.")

    async def get_next_key(self) -> Optional[Key]:
        """按 Round Robin 获取下一个 ACTIVE 的 Key"""
        async with self._lock:
            if not self._keys:
                return None
            
            num_keys = len(self._keys)
            # 遍历最多一圈，寻找 ACTIVE Key
            for _ in range(num_keys):
                key = self._keys[self._index]
                self._index = (self._index + 1) % num_keys
                
                if key.check_status() == KeyStatus.ACTIVE:
                    return key
            
            return None

    async def execute_with_retry(self, func: Callable[[str], Any], *args, **kwargs) -> Any:
        """执行带重试逻辑的 API 调用"""
        max_retries = len(self._keys) if self._keys else 1
        tried_keys = set()

        for attempt in range(max_retries):
            key = await self.get_next_key()
            if not key:
                logger.error("No active Tavily API keys available.")
                raise RuntimeError("No active API keys available in the pool.")

            if key.raw_key in tried_keys:
                # 已经尝试过池中所有的活跃 Key
                break
            
            tried_keys.add(key.raw_key)
            logger.debug(f"Attempting with key {key.label} (Attempt {attempt + 1}/{max_retries})")

            try:
                # 假设 func 是一个接受 api_key 参数的函数
                # 注意：实际调用时需要传入 key.raw_key
                return await func(key.raw_key, *args, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                logger.warning(f"Key {key.label} failed: {e}")

                if "429" in error_msg or "rate limit" in error_msg:
                    logger.warning(
                        f"[Key限流] 第 {key.position} 个 Key（尾号 {key.tail}）触发限流，"
                        f"进入 60s 冷却。原始错误: {e}"
                    )
                    key.set_cooldown(60)  # 默认冷却 60 秒
                elif "401" in error_msg or "unauthorized" in error_msg or "invalid" in error_msg:
                    logger.error(
                        f"[Key失效] 第 {key.position} 个 Key（尾号 {key.tail}）鉴权失败，"
                        f"已标记为 ERROR。原始错误: {e}"
                    )
                    key.status = KeyStatus.ERROR
                # 其它 5xx / 网络异常：仅 warning，不改状态

                # 如果是最后一次尝试，则抛出异常
                if attempt == max_retries - 1:
                    raise e

                # 继续尝试下一个 Key
                continue

        raise RuntimeError("All available keys failed or no active keys found.")

    @property
    def all_keys(self) -> List[Key]:
        return self._keys
