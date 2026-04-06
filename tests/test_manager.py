import asyncio
import unittest
import sys
import os

# 将项目根目录加入路径以方便导入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.key import Key, KeyStatus
from app.core.manager import KeyPoolManager

class TestKeyPoolManager(unittest.IsolatedAsyncioTestCase):
    async def test_round_robin_scheduling(self):
        """测试轮询调度逻辑"""
        keys = [Key("key1"), Key("key2"), Key("key3")]
        manager = KeyPoolManager(keys)
        
        # 第一次调度
        k1 = await manager.get_next_key()
        self.assertEqual(k1.raw_key, "key1")
        
        # 第二次调度
        k2 = await manager.get_next_key()
        self.assertEqual(k2.raw_key, "key2")
        
        # 第三次调度
        k3 = await manager.get_next_key()
        self.assertEqual(k3.raw_key, "key3")
        
        # 第四次回到第一个
        k4 = await manager.get_next_key()
        self.assertEqual(k4.raw_key, "key1")

    async def test_skip_inactive_keys(self):
        """测试跳过不活跃的 Key"""
        keys = [Key("key1"), Key("key2"), Key("key3")]
        manager = KeyPoolManager(keys)
        
        # 将 key2 设为 429 冷却状态
        keys[1].set_cooldown(60)
        
        # 第一次调度 key1
        k1 = await manager.get_next_key()
        self.assertEqual(k1.raw_key, "key1")
        
        # key2 应被跳过，直接返回 key3
        k3 = await manager.get_next_key()
        self.assertEqual(k3.raw_key, "key3")

if __name__ == "__main__":
    unittest.main()
