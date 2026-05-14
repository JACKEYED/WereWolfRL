# 文件作用：狼人杀小镇中的 Agent 运行时对象，保存人设、位置、动作、LLM 和记忆状态。

import os

from modules import memory, prompt, utils
from modules.model.llm_model import create_llm_model


class Agent:
    def __init__(self, config, maze, conversation, logger):
        self.name = config["name"]
        self.maze = maze
        self.conversation = conversation
        self.logger = logger
        self._llm = None

        self.think_config = config["think"]
        self.spatial = memory.Spatial(**config["spatial"])
        self.schedule = memory.Schedule(**config.get("schedule", {}))
        self.scratch = prompt.Scratch(self.name, config["currently"], config["scratch"])
        self.status = utils.update_dict({"poignancy": 0}, config.get("status", {}))
        self.concepts = []
        self.chats = config.get("chats", [])
        self.last_record = utils.get_timer().daily_duration()

        if config.get("associate", {}).get("disabled"):
            self.associate = memory.NullAssociate()
        else:
            self.associate = memory.Associate(
                os.path.join(config["storage_root"], "associate"),
                **config["associate"],
            )

        if "action" in config:
            self.action = memory.Action.from_dict(config["action"])
        else:
            tile = maze.tile_at(config["coord"])
            address = tile.get_address("game_object", as_list=True)
            self.action = memory.Action(
                memory.Event(self.name, address=address),
                memory.Event(address[-1], address=address),
            )

        self.coord = None
        self.path = []
        self.move(config["coord"], config.get("path"))
        if self.coord is None:
            self.coord = config["coord"]

    def abstract(self):
        info = {
            "name": self.name,
            "currently": self.scratch.currently,
            "tile": self.maze.tile_at(self.coord).abstract(),
            "status": self.status,
            "chats": self.chats,
            "action": self.action.abstract(),
            "associate": self.associate.abstract(),
        }
        if self.llm_available():
            info["llm"] = self._llm.get_summary()
        return info

    def __str__(self):
        return utils.dump_dict(self.abstract())

    def reset(self):
        if not self._llm:
            self._llm = create_llm_model(self.think_config["llm"])

    def think(self, status, agents):
        self.move(status["coord"], status.get("path"))
        return {
            "name": self.name,
            "path": [],
            "emojis": {
                self.name: {
                    "emoji": self.get_event().emoji,
                    "coord": self.coord,
                }
            },
        }

    def move(self, coord, path=None):
        events = {}

        def update_tile(tile_coord):
            tile = self.maze.tile_at(tile_coord)
            if not self.action:
                return {}
            if not tile.update_events(self.get_event()):
                tile.add_event(self.get_event())
            obj_event = self.get_event(False)
            if obj_event:
                self.maze.update_obj(tile_coord, obj_event)
            return {event: tile_coord for event in tile.get_events()}

        if self.coord and self.coord != coord:
            tile = self.get_tile()
            tile.remove_events(subject=self.name)
            if tile.has_address("game_object"):
                address = tile.get_address("game_object")
                self.maze.update_obj(self.coord, memory.Event(address[-1], address=address))
            events.update({event: self.coord for event in tile.get_events()})
        if not path:
            events.update(update_tile(coord))
        self.coord = coord
        self.path = path or []
        return events

    def get_tile(self):
        return self.maze.tile_at(self.coord)

    def get_event(self, as_act=True):
        return self.action.event if as_act else self.action.obj_event

    def llm_available(self):
        return bool(self._llm and self._llm.is_available())

    def to_dict(self, with_action=True):
        info = {
            "status": self.status,
            "schedule": self.schedule.to_dict(),
            "associate": self.associate.to_dict(),
            "chats": self.chats,
            "currently": self.scratch.currently,
        }
        if with_action:
            info["action"] = self.action.to_dict()
        return info
