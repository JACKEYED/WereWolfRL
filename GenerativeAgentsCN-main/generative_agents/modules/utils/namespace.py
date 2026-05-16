# 文件作用：
#   - GenerativeAgentsMap：进程级全局键值表（用于兜底 + 旧代码兼容）
#   - ActiveGameContext：thread-local 当前活跃 game，用于支持多线程并行跑多局
#     8 路并行 GRPO collection 时，每个线程在跑自己那一局前把 active game 切到本局，
#     这样 utils.get_timer() 等老 API 会自动拿到本线程那一局的 timer，互不串扰。

from typing import Any, Optional
import copy
import threading


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


class ActiveGameContext:
    """当前线程正在跑的 Game。让 utils.get_timer() 等老 API 自动落到正确的 game.timer。

    用法（线程内）：
        with ActiveGameContext.bind(game):
            game.run()
    或显式：
        ActiveGameContext.set(game)
        try: ...
        finally: ActiveGameContext.clear()
    """

    _local = threading.local()

    @classmethod
    def set(cls, game: Any) -> None:
        cls._local.game = game

    @classmethod
    def get(cls) -> Optional[Any]:
        return getattr(cls._local, "game", None)

    @classmethod
    def clear(cls) -> None:
        if hasattr(cls._local, "game"):
            del cls._local.game

    @classmethod
    def bind(cls, game: Any):
        """contextmanager 版：with ActiveGameContext.bind(game):"""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            prev = cls.get()
            cls.set(game)
            try:
                yield game
            finally:
                if prev is None:
                    cls.clear()
                else:
                    cls.set(prev)

        return _ctx()
