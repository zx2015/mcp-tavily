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
    def __init__(self, raw_key: str, label: Optional[str] = None):
        self.raw_key = raw_key
        self.label = label or self._mask_key(raw_key)
        self.status = KeyStatus.ACTIVE
        self.cooldown_until: Optional[datetime] = None
        self.usage: int = 0
        self.limit: int = 0
        self._lock = threading.Lock()

    def _mask_key(self, key: str) -> str:
        if len(key) <= 8:
            return "****"
        return f"{key[:4]}...{key[-4:]}"

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
        return f"<Key label={self.label} status={self.status.value}>"
