from enum import Enum
from datetime import datetime, timedelta
import threading
from typing import Optional


class KeyStatus(Enum):
    ACTIVE = "ACTIVE"
    COOLDOWN = "COOLDOWN"
    EXHAUSTED = "EXHAUSTED"
    ERROR = "ERROR"


class Key:
    def __init__(self, raw_key: str, label: Optional[str] = None, position: Optional[int] = None):
        self.raw_key = raw_key
        self.label = label or self._mask_key(raw_key)
        # 配置顺序中的位置（1-based）。由 ConfigManager 在解析时赋值；热加载时重新分配。
        # 用于在日志中明确"是第几个 Key 失效"，便于用户在 .env 中快速定位。
        self.position: Optional[int] = position
        self.status = KeyStatus.ACTIVE
        self.cooldown_until: Optional[datetime] = None
        self.usage: int = 0
        self.limit: int = 0
        # 使用可重入锁：set_exhausted/set_active 会被 update_usage/check_status
        # 在已持有该锁的情况下再次调用，普通 Lock 会导致死锁
        self._lock = threading.RLock()

    def _mask_key(self, key: str) -> str:
        if len(key) <= 8:
            return "****"
        return f"{key[:4]}...{key[-4:]}"

    @property
    def tail(self) -> str:
        """返回 Key 的末 6 位脱敏值（不足 6 位时返回全 *）。

        与 ``_mask_key`` 不同：``_mask_key`` 输出"前 4...后 4"双侧脱敏，
        而 ``tail`` 保留足够的信息用于人工对位但不暴露前缀。仅用于日志展示。
        """
        if len(self.raw_key) <= 6:
            return "*" * len(self.raw_key)
        return self.raw_key[-6:]

    def set_cooldown(self, duration_seconds: int = 60):
        with self._lock:
            self.status = KeyStatus.COOLDOWN
            self.cooldown_until = datetime.now() + timedelta(seconds=duration_seconds)

    def set_exhausted(self):
        with self._lock:
            self.status = KeyStatus.EXHAUSTED

    def set_active(self):
        with self._lock:
            self.status = KeyStatus.ACTIVE
            self.cooldown_until = None

    def check_status(self) -> KeyStatus:
        with self._lock:
            if self.status == KeyStatus.COOLDOWN:
                if self.cooldown_until and datetime.now() >= self.cooldown_until:
                    self.set_active()
            return self.status

    def update_usage(self, usage: int, limit: int):
        with self._lock:
            self.usage = usage
            self.limit = limit
            if usage >= limit > 0:
                self.set_exhausted()
            elif self.status == KeyStatus.EXHAUSTED and usage < limit:
                self.set_active()

    def __repr__(self):
        pos = f" pos=#{self.position}" if self.position is not None else ""
        return f"<Key label={self.label}{pos} status={self.status.value}>"
