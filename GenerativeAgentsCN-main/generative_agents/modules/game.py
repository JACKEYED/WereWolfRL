# 文件作用：Game 类（小镇地图 + Agent 集合 + 对话记录 + 本局 Timer）+ GameRegistry（按 name 管理多 game）。
# 单进程多线程并行：每个线程跑一个 Game，通过 ActiveGameContext 绑定，使老 utils.get_timer() 等 API 自动落到本线程的 game。

import copy
import os
import threading
from typing import Dict, List, Optional

from modules import utils
from modules.utils import GenerativeAgentsMap, GenerativeAgentsKey, ActiveGameContext
from modules.utils.timer import Timer

from .maze import Maze
from .agent import Agent


class Game:
    """The Game"""

    def __init__(self, name, static_root, config, conversation, logger=None):
        self.name = name
        self.static_root = static_root
        self.record_iterval = config.get("record_iterval", 30)
        self.logger = logger or utils.IOLogger()
        # 本局自己的 Timer（之前是进程全局），让多线程并发跑多局时各自推进各自的时间
        self.timer = Timer(start=(config.get("time", {}) or {}).get("start"))
        # 临时把本游戏挂为活跃，确保下面构造 Maze / Agent 时 utils.get_timer() 拿到自己的 timer
        with ActiveGameContext.bind(self):
            self.maze = Maze(self.load_static(config["maze"]["path"]), self.logger)
            self.conversation = conversation
            self.agents = {}
            agent_base = config.get("agent_base", {})
            storage_root = os.path.join(f"results/checkpoints/{name}", "storage")
            if not os.path.isdir(storage_root):
                os.makedirs(storage_root)
            for agent_name, agent in config["agents"].items():
                agent_config = utils.update_dict(
                    copy.deepcopy(agent_base), self.load_static(agent["config_path"])
                )
                agent_config = utils.update_dict(agent_config, agent)
                agent_config["storage_root"] = os.path.join(storage_root, agent_name)
                self.agents[agent_name] = Agent(
                    agent_config, self.maze, self.conversation, self.logger
                )

    def get_agent(self, name):
        return self.agents[name]

    def agent_think(self, name, status):
        agent = self.get_agent(name)
        plan = agent.think(status, self.agents)
        info = {
            "currently": agent.scratch.currently,
            "associate": agent.associate.abstract(),
            "concepts": {c.node_id: c.abstract() for c in agent.concepts},
            "chats": [
                {"name": "self" if n == agent.name else n, "chat": c}
                for n, c in agent.chats
            ],
            "action": agent.action.abstract(),
            "schedule": agent.schedule.abstract(),
            "address": agent.get_tile().get_address(as_list=False),
        }
        if (self.timer.daily_duration() - agent.last_record) > self.record_iterval:
            info["record"] = True
            agent.last_record = self.timer.daily_duration()
        else:
            info["record"] = False
        if agent.llm_available():
            info["llm"] = agent._llm.get_summary()
        title = "{}.summary @ {}".format(
            name, self.timer.get_date("%Y%m%d-%H:%M:%S")
        )
        self.logger.info("\n{}\n{}\n".format(utils.split_line(title), agent))
        return {"plan": plan, "info": info}

    def load_static(self, path):
        return utils.load_dict(os.path.join(self.static_root, path))

    def reset_game(self):
        with ActiveGameContext.bind(self):
            for a_name, agent in self.agents.items():
                agent.reset()
                title = "{}.reset".format(a_name)
                self.logger.info("\n{}\n{}\n".format(utils.split_line(title), agent))


# =========================================================================
# Registry：按 name 管理多个 Game，支持单进程多 game
# =========================================================================
class GameRegistry:
    """所有活跃 Game 的注册表。线程安全。"""

    _games: Dict[str, Game] = {}
    _lock = threading.Lock()

    @classmethod
    def create(cls, name, static_root, config, conversation, logger=None) -> Game:
        with cls._lock:
            if name in cls._games:
                raise ValueError(f"game '{name}' 已存在；先 GameRegistry.remove() 再创建。")
            game = Game(name, static_root, config, conversation, logger=logger)
            cls._games[name] = game
        # 默认把新建的 game 设为本线程活跃 game（兼容旧 get_game() 无参形式）
        ActiveGameContext.set(game)
        # 旧代码若直接读 GenerativeAgentsMap.GAME 也要能拿到（向后兼容）
        GenerativeAgentsMap.set(GenerativeAgentsKey.GAME, game)
        return game

    @classmethod
    def get(cls, name: str) -> Optional[Game]:
        return cls._games.get(name)

    @classmethod
    def activate(cls, name: str) -> Game:
        """把 name 对应的 game 切到本线程活跃位（用于线程内显式切换）。"""
        game = cls._games.get(name)
        if not game:
            raise KeyError(f"game '{name}' 不存在")
        ActiveGameContext.set(game)
        return game

    @classmethod
    def remove(cls, name: str) -> bool:
        with cls._lock:
            game = cls._games.pop(name, None)
        if game is not None and ActiveGameContext.get() is game:
            ActiveGameContext.clear()
        return game is not None

    @classmethod
    def list_ids(cls) -> List[str]:
        with cls._lock:
            return list(cls._games.keys())

    @classmethod
    def clear(cls) -> None:
        """全部清空（测试用）。"""
        with cls._lock:
            cls._games.clear()
        ActiveGameContext.clear()


# =========================================================================
# 向后兼容的旧 API
# =========================================================================
def create_game(name, static_root, config, conversation, logger=None) -> Game:
    """创建并注册一个 Game。如果同名已存在会抛 ValueError。"""
    return GameRegistry.create(name, static_root, config, conversation, logger=logger)


def get_game(name: Optional[str] = None) -> Optional[Game]:
    """取 game。
    - name 给定：从 registry 按 name 取
    - name 为 None：返回当前线程活跃 game（旧代码兼容路径）
    """
    if name is not None:
        return GameRegistry.get(name)
    return ActiveGameContext.get()
