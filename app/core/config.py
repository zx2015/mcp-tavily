import os
import time
import threading
import logging
from typing import List, Callable
from app.core.key import Key

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, env_file: str = ".env"):
        self.env_file = env_file
        self._last_modified_time = 0
        self._keys: List[Key] = []
        self._callbacks: List[Callable[[List[Key]], None]] = []
        self._lock = threading.Lock()
        
        # 初始加载
        self.reload()

    def register_callback(self, callback: Callable[[List[Key]], None]):
        """注册当 Key 列表更新时的回调函数"""
        with self._lock:
            self._callbacks.append(callback)

    def _parse_keys(self) -> List[Key]:
        """从环境变量中解析 Key"""
        keys_str = os.getenv("TAVILY_API_KEYS", "")
        if not keys_str:
            return []

        raw_keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        # 简单去重并保留顺序
        seen = set()
        unique_keys = []
        # 使用 enumerate(start=1) 给每个 Key 分配 1-based 配置位置，
        # 用于日志中"第 N 个 Key"的输出，便于用户在 .env 中定位。
        for pos, k in enumerate(raw_keys, start=1):
            if k not in seen:
                unique_keys.append(Key(k, position=pos))
                seen.add(k)
        return unique_keys

    def reload(self):
        """手动重新加载 .env 并更新 Key 列表"""
        # 如果存在 .env 文件，尝试读取（这里使用简单方式加载，不依赖 python-dotenv 以保持轻量）
        if os.path.exists(self.env_file):
            with open(self.env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            self._last_modified_time = os.path.getmtime(self.env_file)

        new_keys = self._parse_keys()
        
        with self._lock:
            # 比较 Key 是否发生变化（仅通过 raw_key 比较）
            old_raw_keys = [k.raw_key for k in self._keys]
            new_raw_keys = [k.raw_key for k in new_keys]
            
            if old_raw_keys != new_raw_keys:
                logger.info(f"Detected config change. Loading {len(new_keys)} keys.")
                self._keys = new_keys
                for callback in self._callbacks:
                    callback(self._keys)

    def start_watching(self, interval_seconds: int = 5):
        """启动后台线程监听 .env 变化"""
        def _watch():
            while True:
                if os.path.exists(self.env_file):
                    mtime = os.path.getmtime(self.env_file)
                    if mtime > self._last_modified_time:
                        logger.info(f"File {self.env_file} changed, reloading...")
                        self.reload()
                time.sleep(interval_seconds)

        watcher_thread = threading.Thread(target=_watch, daemon=True)
        watcher_thread.start()

    @property
    def keys(self) -> List[Key]:
        with self._lock:
            return self._keys
