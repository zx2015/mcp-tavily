import asyncio
import logging
from typing import List, Optional, Callable, Any
from app.core.key import Key, KeyStatus

logger = logging.getLogger(__name__)

# 网络层错误关键字：DNS 解析失败、连接被拒绝等。这类错误与具体 Key 无关——所有 Key 请求的都是
# 同一个 api.tavily.com 域名，一旦本地/容器 DNS 解析出现瞬时抖动，轮换到下一个 Key 同样会失败，
# 白白耗尽整个 Key 轮询预算却始终无法恢复。因此这类错误不适合走"切换 Key"策略，而是在同一个
# Key 上做几次短暂指数退避的快速重试，给瞬时网络抖动（通常几秒内自愈）留出恢复时间。
_NETWORK_ERROR_KEYWORDS = (
    "nameresolutionerror",
    "failed to resolve",
    "temporary failure in name resolution",
    "no address associated with hostname",
    "max retries exceeded",
    "connectionerror",
    "connect timeout",
    "connecttimeout",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "gaierror",
)

# 针对网络层错误，在同一个 Key 上做的最大额外快速重试次数（不计入 Key 轮询预算 max_retries）
NETWORK_ERROR_MAX_RETRIES = 2
# 指数退避基数（秒）：第 1 次重试等待 0.5s，第 2 次等待 1.0s，以此类推
NETWORK_ERROR_BACKOFF_BASE = 0.5


def _is_network_error(exc: Exception) -> bool:
    """判断异常是否为网络层错误（DNS 解析失败 / 连接失败等），而非 Tavily API 返回的业务错误。

    网络层错误的特征是：无论使用哪个 Key，请求都会在建立连接这一步就失败，与 Key 本身是否
    有效、是否限流无关。因此不应像 429/401 那样修改 Key 状态（冷却/标记失效），而是应该
    在原地快速重试，等待网络自愈。
    """
    error_msg = str(exc).lower()
    return any(keyword in error_msg for keyword in _NETWORK_ERROR_KEYWORDS)


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

            # 网络层错误在同一个 Key 上做的快速重试计数（不消耗 Key 轮询预算 max_retries）
            network_retry = 0

            while True:
                try:
                    # 假设 func 是一个接受 api_key 参数的函数
                    # 注意：实际调用时需要传入 key.raw_key
                    return await func(key.raw_key, *args, **kwargs)
                except Exception as e:
                    error_msg = str(e).lower()

                    if _is_network_error(e) and network_retry < NETWORK_ERROR_MAX_RETRIES:
                        # DNS 解析失败/连接失败等网络层错误：所有 Key 共享同一目标域名，
                        # 切换 Key 无法规避此类故障。原地快速重试，给瞬时抖动留出自愈时间。
                        network_retry += 1
                        backoff = NETWORK_ERROR_BACKOFF_BASE * (2 ** (network_retry - 1))
                        logger.warning(
                            f"[网络错误] 第 {key.position} 个 Key（尾号 {key.tail}）遇到网络层错误"
                            f"（DNS 解析/连接失败），{backoff:.1f}s 后原地快速重试"
                            f"（{network_retry}/{NETWORK_ERROR_MAX_RETRIES}）。原始错误: {e}"
                        )
                        await asyncio.sleep(backoff)
                        continue  # 同一个 Key 再试一次，不进入下方 429/401 判断，也不轮换 Key

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
                    # 其它 5xx / 网络异常（已用尽快速重试预算）：仅 warning，不改状态

                    # 如果是最后一次尝试，则抛出异常
                    if attempt == max_retries - 1:
                        raise e

                    # 跳出网络重试内层循环，继续尝试下一个 Key
                    break

        raise RuntimeError("All available keys failed or no active keys found.")

    @property
    def all_keys(self) -> List[Key]:
        return self._keys
