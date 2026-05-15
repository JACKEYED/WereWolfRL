# 文件作用：内存中的对局会话管理 + 事件总线。
# 当前架构下 modules/game.py 使用全局单例，所以同一进程只能跑一局；
# 这里仍按 game_id 维护字典，但同一时间只有一份 director 是 live 的。

import asyncio
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional


@dataclass
class GameSession:
    id: str
    name: str
    created_at: str
    director: object  # WerewolfDirector，避免在此处 import 触发 pydantic
    phase_index: int = 0  # 已推进到的阶段序号（用于 step-by-step 模式）
    finished: bool = False
    # 订阅者：每个 WebSocket 连接对应一个异步队列
    subscribers: List["asyncio.Queue[dict]"] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionRegistry:
    """所有活动对局的注册表 + 事件总线。线程安全。"""

    def __init__(self):
        self._sessions: Dict[str, GameSession] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # 用于跨线程派发

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def create(self, name: str, director) -> GameSession:
        session_id = uuid.uuid4().hex[:12]
        sess = GameSession(
            id=session_id,
            name=name,
            created_at=datetime.now().isoformat(timespec="seconds"),
            director=director,
        )
        with self._lock:
            self._sessions[session_id] = sess
        self._wire_event_hook(sess)
        return sess

    def get(self, game_id: str) -> Optional[GameSession]:
        with self._lock:
            return self._sessions.get(game_id)

    def list_all(self) -> List[GameSession]:
        with self._lock:
            return list(self._sessions.values())

    def remove(self, game_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(game_id, None) is not None

    def _wire_event_hook(self, sess: GameSession) -> None:
        """让 director.add_record 触发后顺手把事件 push 给所有订阅者。"""
        director = sess.director
        original_add_record = director.add_record

        def patched_add_record(
            scope: str,
            phase: str,
            text: str,
            *,
            actors=None,
            location: Optional[str] = None,
        ):
            original_add_record(scope, phase, text, actors=actors, location=location)
            event = {
                "type": "record",
                "scope": scope,
                "phase": phase,
                "text": text,
                "actors": list(actors or []),
                "location": location or "",
                "day": getattr(director, "day", 0),
            }
            self._dispatch(sess, event)

        director.add_record = patched_add_record  # type: ignore[assignment]

    def _dispatch(self, sess: GameSession, event: dict) -> None:
        """把事件投递到本会话的所有订阅队列。可在任意线程调用。"""
        if not self._loop:
            return
        for queue in list(sess.subscribers):
            try:
                self._loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception:
                pass

    def subscribe(self, sess: GameSession) -> "asyncio.Queue[dict]":
        queue: asyncio.Queue = asyncio.Queue()
        sess.subscribers.append(queue)
        return queue

    def unsubscribe(self, sess: GameSession, queue: "asyncio.Queue[dict]") -> None:
        try:
            sess.subscribers.remove(queue)
        except ValueError:
            pass


# 全局单例。
registry = SessionRegistry()
