# 文件作用：狼人杀导演主类的薄壳。
# 状态拥有 + 主循环 + game/maze 接口在此；规则/记录/LLM/阶段逻辑被拆到平级模块。
# 拆分关系（路 1 重构）：
#   - locations.py  地点常量
#   - rules.py      规则常量与纯函数
#   - player.py     玩家数据 + 兜底发言
#   - text_utils.py 文本清洗 / 选项匹配 / 姓名拼接
#   - recorder.py   日志、对话、检查点、报告
#   - llm_io.py     prompt 构造 + ask_text / ask_choice
#   - phases/night.py | day.py | social.py 阶段逻辑

import json
import os
import random
from typing import Dict, Iterable, List, Optional, Sequence

from modules import memory, utils
from modules.game import create_game, get_game

from modules.werewolf.locations import (
    LOCATIONS,
    SOCIAL_SPOTS,
    SOCIAL_SPOT_KEYS,
    location_display_from_address,
    shichen,
)
from modules.werewolf.player import WerewolfPlayer, role_brief as _role_brief
from modules.werewolf.rules import (
    ROLE_DECK,
    SAFETY_DAY_LIMIT,
    check_winner,
    majority_choice as _majority_choice,
)
from modules.werewolf.text_utils import clean_text as _clean_text, join_names as _join_names
from modules.werewolf import recorder as _recorder
from modules.werewolf import llm_io as _llm_io
from modules.werewolf.phases import night as _night, day as _day, social as _social


# 默认玩家名单（江南古镇 12 民国人）；可被 start.py 覆盖。
DEFAULT_WEREWOLF_PLAYERS: List[str] = [
    "陈砚秋", "苏蘅", "林宛娘", "周文卿",
    "孟雨棠", "沈鹤年", "阿福", "温知微",
    "白潜舟", "徐慎之", "柳青禾", "吴掌柜",
]


def load_agent_base(config_path: str = "data/config.json") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)["agent"]


def build_werewolf_config(
    start_time: str,
    stride: int,
    players: Sequence[str],
    agent_base: dict,
    assets_root: str = os.path.join("assets", "village"),
) -> dict:
    config = {
        "stride": stride,
        "time": {"start": start_time},
        "maze": {"path": os.path.join(assets_root, "maze.json")},
        "agent_base": agent_base,
        "agents": {},
        "werewolf_mode": True,
    }
    for name in players:
        config["agents"][name] = {
            "config_path": os.path.join(
                assets_root, "agents", name.replace(" ", "_"), "agent.json"
            )
        }
    return config


class WerewolfDirector:
    """空间狼人杀的导演：拥有状态、跑主循环、对 game/maze 做接口适配。"""

    # ----- 从拆出去的模块绑定方法 -----
    # 记录/序列化
    add_record = _recorder.add_record
    record_dialogue = _recorder.record_dialogue
    safe_broadcast = _recorder.safe_broadcast
    safe_remember = _recorder.safe_remember
    state_dict = _recorder.state_dict
    save_checkpoint = _recorder.save_checkpoint
    write_report = _recorder.write_report
    # LLM IO
    ask_text = _llm_io.ask_text
    ask_choice = _llm_io.ask_choice
    build_agent_prompt = _llm_io.build_agent_prompt
    # 阶段
    night_phase = _night.night_phase
    werewolf_action = _night.werewolf_action
    guard_action = _night.guard_action
    seer_action = _night.seer_action
    witch_action = _night.witch_action
    hunter_wait_action = _night.hunter_wait_action
    day_phase = _day.day_phase
    debate_phase = _day.debate_phase
    vote_phase = _day.vote_phase
    free_social_window = _social.free_social_window

    def __init__(
        self,
        name: str,
        static_root: str,
        checkpoints_folder: str,
        config: dict,
        *,
        seed: Optional[int] = None,
        role_map: Optional[Dict[str, str]] = None,
        use_llm: bool = True,
        write_memory: bool = True,
        debate_turns: int = 4,
        logger=None,
    ):
        self.name = name
        self.static_root = static_root
        self.checkpoints_folder = checkpoints_folder
        self.config = config
        self.random = random.Random(seed)
        self.role_map = role_map
        self.use_llm = use_llm
        self.write_memory = write_memory
        self.debate_turns = debate_turns
        self.logger = logger or utils.create_io_logger("info")

        os.makedirs(checkpoints_folder, exist_ok=True)
        self.conversation_log = os.path.join(checkpoints_folder, "conversation.json")
        if os.path.exists(self.conversation_log):
            with open(self.conversation_log, "r", encoding="utf-8") as f:
                conversation = json.load(f)
        else:
            conversation = {}

        create_game(name, static_root, config, conversation, logger=self.logger)
        self.game = get_game()
        self.game.reset_game()

        self.players_order: List[str] = list(config["agents"].keys())
        self.players: Dict[str, WerewolfPlayer] = {}
        self.private_log: Dict[str, List[str]] = {n: [] for n in self.players_order}
        self.public_log: List[str] = []
        self.phase_records: List[dict] = []
        self.seer_checks: Dict[str, Dict[str, str]] = {}
        self.witch_antidote = True
        self.witch_poison = True
        self.guard_last_target: Optional[str] = None
        self.day = 0
        self.step = int(config.get("step", 0))
        self.winner: Optional[str] = None
        self.gossip_mill = None
        try:
            from modules.gossip import GossipMill

            self.gossip_mill = GossipMill(self.random)
        except Exception as exc:
            self.logger.warning(f"流言模块未加载：{exc}")

    # =========================================================================
    # 主循环
    # =========================================================================
    def run(self) -> dict:
        self.setup()
        self.free_social_window("开场申时（黄昏踩点）", rounds=3)

        for day in range(1, SAFETY_DAY_LIMIT + 1):
            self.day = day
            self.night_phase(day)
            if self.check_win("子时结算"):
                break

            self.day_phase(day)
            if self.check_win("辰时议会"):
                break

            self.free_social_window(shichen(day, "申时余韵"), rounds=2)

        if not self.winner:
            self.add_record(
                "public",
                "游戏结束",
                f"达到内部安全上限 {SAFETY_DAY_LIMIT} 天，游戏暂停。当前仍有 {len(self.alive_names())} 名玩家存活。",
            )
        self.write_report()
        self.save_checkpoint("结束")
        return self.state_dict("结束")

    def setup(self) -> None:
        self.assign_roles()
        for name in self.players_order:
            brief = self.role_brief(name)
            self.private_log[name].append(brief)
            self.safe_remember(name, brief, node_type="thought", poignancy=9)
            self.move_agent(
                name,
                self.home_address(name),
                "在房间里查看自己的狼人杀秘密身份牌",
                phase="开局",
                duration=10,
                emoji="身份",
            )

        self.add_record(
            "public",
            "开局",
            "江南古镇风云骤起。12 名镇民暗中收到身份牌，白日议政广场，黑夜各归其所，狼影潜行。",
        )
        self.save_checkpoint("开局")

    def assign_roles(self) -> None:
        if len(self.players_order) != len(ROLE_DECK):
            raise ValueError("12人狼人杀需要正好12名玩家。")

        if self.role_map:
            missing = [name for name in self.players_order if name not in self.role_map]
            if missing:
                raise ValueError(f"role_map 缺少玩家：{', '.join(missing)}")
            roles = [self.role_map[name] for name in self.players_order]
            if sorted(roles) != sorted(ROLE_DECK):
                raise ValueError("role_map 必须包含4狼、预言家、女巫、猎人、守卫、4村民。")
        else:
            roles = ROLE_DECK[:]
            self.random.shuffle(roles)
            self.role_map = dict(zip(self.players_order, roles))

        for name in self.players_order:
            self.players[name] = WerewolfPlayer(name=name, role=self.role_map[name])

    # =========================================================================
    # 胜负与死亡
    # =========================================================================
    def check_win(self, phase: str) -> bool:
        if self.winner:
            return True
        wolves = self.alive_names(role="werewolf")
        good = [n for n in self.alive_names() if self.players[n].role != "werewolf"]
        self.winner = check_winner(wolves, good)
        if self.winner:
            self.add_record(
                "public",
                phase,
                f"游戏结束，{self.winner}获胜。存活狼人：{self.join_names(wolves) or '无'}；"
                f"存活好人：{self.join_names(good) or '无'}。",
            )
            return True
        return False

    def kill_player(self, name: str, reason: str, phase: str) -> None:
        player = self.players[name]
        if not player.alive:
            return
        player.alive = False
        player.death_reason = reason
        player.death_day = self.day
        self.move_agent(name, LOCATIONS["graveyard"], "棺木抬出镇外，于乱葬岗等待最终复盘", phase, 999, "出局")
        self.add_record("public", phase, f"{name} 已殁，死因：{reason}。身份暂不公开。")
        self.safe_broadcast(f"{name} 已殁，死因：{reason}。身份暂不公开。", phase)

        if player.role == "hunter" and not player.used_hunter_shot:
            # 标准规则：被女巫毒药毒杀的猎人无法触发临死反扑
            if "女巫毒药" in reason:
                player.used_hunter_shot = True
                self.add_record("public", phase, f"{name} 七窍流毒，临死反扑之力尽失。")
            else:
                self.hunter_shot(name, phase)

    def hunter_shot(self, hunter: str, phase: str) -> None:
        player = self.players[hunter]
        player.used_hunter_shot = True
        candidates = self.alive_names()
        if not candidates:
            return

        target = self.ask_choice(
            hunter,
            phase,
            "你是猎人，已殁。临死反扑之机：可指认一名仍存活的玩家与你同葬，或选择放手。",
            ["不开枪"] + candidates,
            fallback=self.heuristic_target(hunter, candidates),
        )
        if target == "不开枪":
            self.add_record("public", phase, f"猎人 {hunter} 临死前放下了手。")
            return

        self.add_record("public", phase, f"猎人 {hunter} 临死反扑，带走 {target}。")
        self.kill_player(target, f"猎人 {hunter} 临死反扑", phase)

    # =========================================================================
    # 状态查询
    # =========================================================================
    def alive_names(self, role: Optional[str] = None) -> List[str]:
        names = [n for n in self.players_order if self.players[n].alive]
        if role:
            names = [n for n in names if self.players[n].role == role]
        return names

    def role_holder(self, role: str, *, alive_only: bool = False) -> Optional[str]:
        for name in self.players_order:
            if self.players[name].role == role and (not alive_only or self.players[name].alive):
                return name
        return None

    def role_brief(self, name: str) -> str:
        player = self.players[name]
        wolf_peers = (
            [n for n in self.players_order if n != name and self.players[n].role == "werewolf"]
            if player.role == "werewolf"
            else []
        )
        return _role_brief(player, wolf_peers)

    def heuristic_target(self, actor: str, candidates: Sequence[str], *, prefer_self: bool = False) -> str:
        candidates = list(candidates)
        if prefer_self and actor in candidates:
            return actor
        player = self.players.get(actor)
        if player and player.role == "werewolf":
            non_wolves = [n for n in candidates if self.players[n].role != "werewolf"]
            if non_wolves:
                return self.random.choice(non_wolves)
        if player and player.role != "werewolf":
            wolves = [n for n in candidates if self.players[n].role == "werewolf"]
            if wolves and not self.use_llm:
                return self.random.choice(wolves)
        return self.random.choice(candidates)

    def majority_choice(self, values: Sequence[str]) -> str:
        return _majority_choice(values, self.random)

    def join_names(self, names: Iterable[str]) -> str:
        return _join_names(names)

    def location_name(self, address: Sequence[str]) -> str:
        return location_display_from_address(address)

    def clean_text(self, value: str, max_chars: int) -> str:
        return _clean_text(value, max_chars)

    # =========================================================================
    # 地图 / 移动接口
    # =========================================================================
    def home_address(self, name: str) -> List[str]:
        agent = self.game.get_agent(name)
        address = agent.spatial.address.get("living_area")
        return address or LOCATIONS["square"]

    def move_many(
        self,
        names: Sequence[str],
        address: Sequence[str],
        describe: str,
        phase: str,
        emoji: str,
    ) -> None:
        for name in names:
            self.move_agent(name, address, describe, phase, duration=10, emoji=emoji)
        self.add_record(
            "movement",
            phase,
            f"{self.join_names(names)} 前往 {self.location_name(address)}，{describe}。",
            actors=names,
            location=self.location_name(address),
        )

    def move_agent(
        self,
        name: str,
        address: Sequence[str],
        describe: str,
        phase: str,
        duration: int,
        emoji: str,
    ) -> None:
        agent = self.game.get_agent(name)
        coord = self.pick_coord(address)
        event = memory.Event(
            name,
            "正在",
            describe,
            describe=f"{name} {describe}",
            address=list(address),
            emoji=emoji,
        )
        obj_event = memory.Event(
            address[-1],
            "被占用",
            name,
            describe=f"{address[-1]} 被{name}用于{describe}",
            address=list(address),
            emoji=emoji,
        )
        agent.action = memory.Action(
            event,
            obj_event,
            start=utils.get_timer().get_date(),
            duration=duration,
        )
        agent.move(coord)
        self.config["agents"].setdefault(name, {})["coord"] = list(agent.coord)

    def pick_coord(self, address: Sequence[str]) -> List[int]:
        tiles = list(self.game.maze.get_address_tiles(list(address)))
        open_tiles = [coord for coord in tiles if not self.game.maze.tile_at(coord).collision]
        occupied = {tuple(agent.coord) for agent in self.game.agents.values() if agent.coord}
        candidates = [coord for coord in open_tiles if tuple(coord) not in occupied] or open_tiles or tiles
        return list(self.random.choice(candidates))
