# 文件作用：提供全局命名空间容器，用于保存当前 Game 和 Timer 实例。

from typing import Any, Optional
import copy


class GenerativeAgentsMap:
    """Global Namespace map for Land"""

    MAP = {}

    @classmethod
    def set(cls, key: str, value: Any):
        cls.MAP[key] = value

    @classmethod
    def get(cls, key: str, default: Optional[Any] = None):
        return cls.MAP.get(key, default)

    @classmethod
    def clone(cls, key: str, default: Optional[Any] = None):
        return copy.deepcopy(cls.get(key, default))

    @classmethod
    def delete(cls, key: str):
        if key in cls.MAP:
            return cls.MAP.pop(key)
        return None

    @classmethod
    def contains(cls, key: str):
        return key in cls.MAP

    @classmethod
    def reset(cls):
        cls.MAP = {}


class GenerativeAgentsKey:
    """Keys for the LandMap"""

    GAME = "game"
    TIMER = "timer"
    MODELS = "models"
