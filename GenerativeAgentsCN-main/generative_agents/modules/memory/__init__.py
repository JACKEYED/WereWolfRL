# 文件作用：导出记忆相关基础类，并提供可跳过向量库的 NullAssociate 测试实现。

from .action import Action
from .event import Event
from .schedule import Schedule
from .spatial import Spatial


class NullAssociate:
    def __init__(self, *args, **kwargs):
        self.memory = {"event": [], "thought": [], "chat": []}

    def abstract(self):
        return {"nodes": 0, "event": [], "thought": [], "chat": []}

    def add_node(self, node_type, event, poignancy, create=None, expire=None, filling=None):
        return None

    def retrieve_events(self, text=None):
        return []

    def retrieve_thoughts(self, text=None):
        return []

    def retrieve_chats(self, name=None):
        return []

    def retrieve_focus(self, focus, retrieve_max=30, reduce_all=True):
        return [] if reduce_all else {text: [] for text in focus}

    def get_relation(self, node):
        return {"node": node, "events": [], "thoughts": []}

    def cleanup_index(self):
        return None

    def to_dict(self):
        return {"disabled": True, "memory": self.memory}

    @property
    def index(self):
        class EmptyIndex:
            nodes_num = 0

        return EmptyIndex()


def __getattr__(name):
    if name in {"Associate", "AssociateRetriever", "Concept"}:
        from .associate import Associate, AssociateRetriever, Concept

        return {
            "Associate": Associate,
            "AssociateRetriever": AssociateRetriever,
            "Concept": Concept,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Action",
    "Event",
    "NullAssociate",
    "Schedule",
    "Spatial",
    "Associate",
    "AssociateRetriever",
    "Concept",
]
