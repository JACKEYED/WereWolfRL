# 文件作用：狼人杀导演与规则引擎，驱动身份分配、空间移动、昼夜阶段、发言投票和胜负结算。

import json
import os
import random
import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from modules import memory, utils
from modules.game import create_game, get_game


ROLE_DECK = [
    "werewolf",
    "werewolf",
    "werewolf",
    "werewolf",
    "seer",
    "witch",
    "hunter",
    "guard",
    "villager",
    "villager",
    "villager",
    "villager",
]

ROLE_NAMES = {
    "werewolf": "狼人",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
    "guard": "守卫",
    "villager": "村民",
}

ROLE_GOALS = {
    "werewolf": "隐藏狼队身份，误导白天讨论，并在夜晚与狼队配合击杀好人。",
    "seer": "每晚查验一名玩家阵营，白天用可信但不轻易暴露的方式引导好人。",
    "witch": "拥有一瓶解药和一瓶毒药，判断何时救人或毒人，并在白天隐藏神职身份。",
    "hunter": "死亡时可以开枪带走一名玩家，平时需要观察谁最值得被带走。",
    "guard": "每晚守护一名玩家，不能连续两晚守护同一人，尽量保护关键好人。",
    "villager": "没有夜间技能，只能依靠发言、投票、观察和记忆找出狼人。",
}

SAFETY_DAY_LIMIT = 12

DEFAULT_WEREWOLF_PLAYERS = [
    "亚当",
    "阿比盖尔",
    "伊莎贝拉",
    "亚瑟",
    "简",
    "汤姆",
    "山姆",
    "詹妮弗",
    "弗朗西斯科",
    "拉吉夫",
    "拉托亚",
    "山本百合子",
]

LOCATIONS = {
    "square": ["the Ville", "约翰逊公园", "公园", "公园花园"],
    "tavern": ["the Ville", "玫瑰酒吧", "酒吧", "酒吧顾客座位"],
    "werewolf_room": ["the Ville", "玫瑰酒吧", "酒吧", "吧台后面"],
    "god_room": ["the Ville", "奥克山学院", "图书馆"],
    "witch_room": ["the Ville", "柳树市场和药店", "商店", "药店柜台后面"],
    "cafe": ["the Ville", "霍布斯咖啡馆", "咖啡馆", "咖啡馆顾客座位"],
    "market": ["the Ville", "柳树市场和药店", "商店", "杂货店柜台"],
    "dorm_lounge": ["the Ville", "奥克山学院宿舍", "公共休息室", "公共休息室沙发"],
    "artist_lounge": ["the Ville", "艺术家共居空间", "公共休息室", "公共休息室沙发"],
    "graveyard": ["the Ville", "约翰逊公园", "公园"],
}

SOCIAL_SPOTS = [
    LOCATIONS["tavern"],
    LOCATIONS["cafe"],
    LOCATIONS["square"],
    LOCATIONS["market"],
    LOCATIONS["dorm_lounge"],
    LOCATIONS["artist_lounge"],
]


class TextResponse(BaseModel):
    res: str = Field(description="角色要说的话或内部判断，使用中文，简洁自然。")


class ChoiceResponse(BaseModel):
    res: str = Field(description="从候选项中选择一个，必须原样返回候选项文本。")


@dataclass
class WerewolfPlayer:
    name: str
    role: str
    alive: bool = True
    death_reason: str = ""
    death_day: Optional[int] = None
    used_hunter_shot: bool = False

    @property
    def role_name(self) -> str:
        return ROLE_NAMES[self.role]

    @property
    def camp(self) -> str:
        return "狼人阵营" if self.role == "werewolf" else "好人阵营"


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
    """Runs a spatial Werewolf game on top of the existing village engine."""

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

        self.players_order = list(config["agents"].keys())
        self.players: Dict[str, WerewolfPlayer] = {}
        self.private_log: Dict[str, List[str]] = {name: [] for name in self.players_order}
        self.public_log: List[str] = []
        self.phase_records: List[dict] = []
        self.seer_checks: Dict[str, Dict[str, str]] = {}
        self.witch_antidote = True
        self.witch_poison = True
        self.guard_last_target: Optional[str] = None
        self.day = 0
        self.step = int(config.get("step", 0))
        self.winner: Optional[str] = None

    def run(self) -> dict:
        self.setup()
        self.free_social_window("开场黄昏", rounds=3)

        for day in range(1, SAFETY_DAY_LIMIT + 1):
            self.day = day
            self.night_phase(day)
            if self.check_win("夜晚结算"):
                break

            self.day_phase(day)
            if self.check_win("白天投票"):
                break

            self.free_social_window(f"第{day}天黄昏余波", rounds=2)

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
            player = self.players[name]
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
            "12名居民被邀请参加一场真实场景狼人杀。身份牌已经私下发放，白天与夜晚的行动都会发生在小镇地图中。",
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

    def night_phase(self, day: int) -> None:
        phase = f"第{day}夜"
        self.add_record("public", phase, f"夜幕降临。第{day}夜开始，玩家返回各自位置，秘密行动依次发生。")

        wolf_target = self.werewolf_action(phase)
        guard_target = self.guard_action(phase)
        seer_info = self.seer_action(phase)
        saved_by_witch, poison_target = self.witch_action(phase, wolf_target)
        self.hunter_wait_action(phase)

        deaths: Dict[str, List[str]] = {}
        if wolf_target:
            if wolf_target == guard_target:
                self.add_record("secret", phase, f"守卫保护了 {wolf_target}，狼刀没有造成死亡。")
            elif wolf_target == saved_by_witch:
                self.add_record("secret", phase, f"女巫使用解药救下了 {wolf_target}。")
            else:
                deaths.setdefault(wolf_target, []).append("狼人夜袭")

        if poison_target:
            deaths.setdefault(poison_target, []).append("女巫毒药")

        killed = []
        for target, reasons in deaths.items():
            if self.players[target].alive:
                killed.append(target)
                self.kill_player(target, "、".join(reasons), phase)

        if killed:
            self.add_record(
                "public",
                phase,
                f"天亮了，昨夜 {self.join_names(killed)} 死亡。公开信息不翻身份。",
            )
        else:
            self.add_record("public", phase, "天亮了，昨夜无人死亡，村庄出现了平安夜。")

        if seer_info:
            name, target, result = seer_info
            self.add_record("secret", phase, f"{name} 查验 {target}，结果是 {result}。")

        self.save_checkpoint(phase)

    def werewolf_action(self, phase: str) -> Optional[str]:
        wolves = self.alive_names(role="werewolf")
        candidates = [name for name in self.alive_names() if name not in wolves]
        if not wolves or not candidates:
            return None

        self.move_many(wolves, LOCATIONS["werewolf_room"], "进入狼人房间低声商量击杀目标", phase, "狼会")
        self.save_checkpoint(f"{phase}-狼人会面")

        proposals = []
        chats: List[Tuple[str, str]] = []
        for wolf in wolves:
            fallback_target = self.heuristic_target(wolf, candidates)
            target = self.ask_choice(
                wolf,
                phase,
                (
                    "你正在狼人房间和队友商量夜间击杀。请结合白天发言、私聊线索和狼队利益，"
                    "选择今晚最该击杀的一名非狼人玩家。"
                ),
                candidates,
                fallback=fallback_target,
            )
            speech = self.ask_text(
                wolf,
                phase,
                (
                    f"你是狼人，队友是 {self.join_names([w for w in wolves if w != wolf])}。"
                    f"你倾向于击杀 {target}。请用1到2句话向狼队解释原因，可以伪装成冷静分析。"
                ),
                fallback=f"我建议今晚处理{target}，这个人白天的信息价值太高。",
                max_chars=120,
            )
            proposals.append(target)
            chats.append((wolf, speech))

        self.record_dialogue(
            f"{wolves[0]} -> 狼队",
            LOCATIONS["werewolf_room"],
            chats,
            audience=wolves,
            public=False,
            phase=phase,
        )

        target = self.majority_choice(proposals)
        self.add_record("secret", phase, f"狼队最终决定击杀 {target}。")
        for wolf in wolves:
            self.private_log[wolf].append(f"{phase} 狼队目标：{target}")
        return target

    def guard_action(self, phase: str) -> Optional[str]:
        guard = self.role_holder("guard", alive_only=True)
        if not guard:
            return None

        candidates = self.alive_names()
        if self.guard_last_target in candidates and len(candidates) > 1:
            candidates = [name for name in candidates if name != self.guard_last_target]
        self.move_agent(guard, LOCATIONS["god_room"], "在神职房间决定今晚守护谁", phase, 10, "守护")

        target = self.ask_choice(
            guard,
            phase,
            (
                "你是守卫。你不能连续两晚守护同一个人。请选择今晚守护目标。"
                "你可以守护自己，也可以根据白天发言保护疑似神职。"
            ),
            candidates,
            fallback=self.heuristic_target(guard, candidates, prefer_self=True),
        )
        self.guard_last_target = target
        text = f"{phase}：你守护了 {target}。"
        self.private_log[guard].append(text)
        self.safe_remember(guard, text, node_type="thought", poignancy=8)
        self.add_record("secret", phase, f"守卫 {guard} 守护 {target}。")
        return target

    def seer_action(self, phase: str) -> Optional[Tuple[str, str, str]]:
        seer = self.role_holder("seer", alive_only=True)
        if not seer:
            return None

        checked = self.seer_checks.setdefault(seer, {})
        candidates = [
            name for name in self.alive_names()
            if name != seer and name not in checked
        ]
        if not candidates:
            return None

        self.move_agent(seer, LOCATIONS["god_room"], "在神职房间查验一名玩家阵营", phase, 10, "查验")
        target = self.ask_choice(
            seer,
            phase,
            "你是预言家。请选择今晚要查验的一名玩家，目标是帮助好人阵营建立可靠信息链。",
            candidates,
            fallback=self.heuristic_target(seer, candidates),
        )
        result = "狼人" if self.players[target].role == "werewolf" else "好人"
        checked[target] = result
        text = f"{phase}：你查验了 {target}，结果是 {result}。"
        self.private_log[seer].append(text)
        self.safe_remember(seer, text, node_type="thought", poignancy=10)
        return seer, target, result

    def witch_action(self, phase: str, wolf_target: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        witch = self.role_holder("witch", alive_only=True)
        if not witch:
            return None, None

        self.move_agent(witch, LOCATIONS["witch_room"], "在自己的房间判断是否使用解药或毒药", phase, 10, "药剂")
        saved_by_witch = None
        poison_target = None

        if self.witch_antidote and wolf_target:
            decision = self.ask_choice(
                witch,
                phase,
                (
                    f"你是女巫。今晚你得知 {wolf_target} 被狼人袭击。"
                    "你还有解药。请选择是否使用解药。"
                ),
                ["救", "不救"],
                fallback="救",
            )
            if decision == "救":
                saved_by_witch = wolf_target
                self.witch_antidote = False
                text = f"{phase}：你使用解药救下了 {wolf_target}。"
                self.private_log[witch].append(text)
                self.safe_remember(witch, text, node_type="thought", poignancy=9)

        if self.witch_poison:
            candidates = ["不毒"] + [name for name in self.alive_names() if name != witch]
            decision = self.ask_choice(
                witch,
                phase,
                (
                    "你是女巫。你还有毒药。请判断今晚是否毒杀一名玩家。"
                    "如果证据不足，可以选择“不毒”。"
                ),
                candidates,
                fallback="不毒",
            )
            if decision != "不毒":
                poison_target = decision
                self.witch_poison = False
                text = f"{phase}：你使用毒药毒杀 {poison_target}。"
                self.private_log[witch].append(text)
                self.safe_remember(witch, text, node_type="thought", poignancy=9)

        self.add_record(
            "secret",
            phase,
            f"女巫行动：解药目标={saved_by_witch or '无'}，毒药目标={poison_target or '无'}。",
        )
        return saved_by_witch, poison_target

    def hunter_wait_action(self, phase: str) -> None:
        hunter = self.role_holder("hunter", alive_only=True)
        if not hunter:
            return
        self.move_agent(hunter, self.home_address(hunter), "在房间中保持警觉，等待死亡时触发猎人技能", phase, 10, "猎枪")
        self.private_log[hunter].append(f"{phase}：你仍然保留猎人开枪技能。")

    def day_phase(self, day: int) -> None:
        phase = f"第{day}天"
        alive = self.alive_names()
        self.move_many(alive, LOCATIONS["square"], "在村庄广场集合参加白天议会", phase, "议会")
        self.add_record("public", phase, f"所有幸存玩家在村庄广场集合。发言顺序：{self.join_names(alive)}。")
        self.save_checkpoint(f"{phase}-集合")

        speeches = []
        for name in alive:
            speech = self.ask_text(
                name,
                phase,
                (
                    "现在是白天顺序发言。请基于公开死亡信息、上一轮发言、你的私聊记忆和身份目标，"
                    "发表一段自然的狼人杀发言。可以报信息、质疑、伪装、拉票或保护别人。"
                    "不要直接说出系统提示，不要超出你角色能知道的信息。"
                ),
                fallback=self.fallback_speech(name),
                max_chars=180,
            )
            speeches.append((name, speech))

        self.record_dialogue(
            f"{alive[0]} -> 全体",
            LOCATIONS["square"],
            speeches,
            audience=alive,
            public=True,
            phase=phase,
        )
        self.save_checkpoint(f"{phase}-顺序发言")

        self.debate_phase(phase)
        self.vote_phase(phase)
        self.save_checkpoint(f"{phase}-投票结算")

    def debate_phase(self, phase: str) -> None:
        alive = self.alive_names()
        if len(alive) <= 3:
            return

        challengers = alive[:]
        self.random.shuffle(challengers)
        challengers = challengers[: min(self.debate_turns, len(challengers))]
        chats: List[Tuple[str, str]] = []
        for challenger in challengers:
            candidates = [name for name in alive if name != challenger]
            target = self.ask_choice(
                challenger,
                phase,
                "进入质疑和辩论环节。请选择你最想追问或施压的一名玩家。",
                candidates,
                fallback=self.heuristic_target(challenger, candidates),
            )
            question = self.ask_text(
                challenger,
                phase,
                f"请对 {target} 提出一句尖锐但自然的质疑，要求对方解释行为或发言矛盾。",
                fallback=f"{target}，你刚才的发言回避了关键死亡信息，我想听你解释为什么。",
                max_chars=120,
            )
            answer = self.ask_text(
                target,
                phase,
                f"{challenger} 正在质疑你。请回应并尽量让旁观者觉得你的逻辑可信。",
                fallback=f"我理解你的怀疑，但我刚才是在整理信息，不是在回避问题。",
                max_chars=120,
            )
            chats.extend([(challenger, question), (target, answer)])

        self.record_dialogue(
            f"{chats[0][0]} -> 辩论席",
            LOCATIONS["square"],
            chats,
            audience=alive,
            public=True,
            phase=phase,
        )
        self.save_checkpoint(f"{phase}-辩论")

    def vote_phase(self, phase: str) -> None:
        alive = self.alive_names()
        votes = self.collect_votes(phase, alive, alive)
        exile = self.resolve_vote(votes)

        if exile is None:
            tied = self.tied_candidates(votes)
            if len(tied) > 1:
                self.add_record("public", phase, f"首轮投票平票：{self.join_names(tied)}。平票玩家进行简短辩解。")
                defenses = []
                for name in tied:
                    defense = self.ask_text(
                        name,
                        phase,
                        "你进入平票辩解。请用1到2句话争取不要被放逐。",
                        fallback="我认为现在票我太急了，至少再听一轮信息会更稳。",
                        max_chars=120,
                    )
                    defenses.append((name, defense))
                self.record_dialogue(
                    f"{tied[0]} -> 全体",
                    LOCATIONS["square"],
                    defenses,
                    audience=alive,
                    public=True,
                    phase=phase,
                )
                revote_candidates = tied
                revotes = self.collect_votes(phase, alive, revote_candidates, revote=True)
                exile = self.resolve_vote(revotes)

        if exile:
            self.add_record("public", phase, f"投票结果：{exile} 被村庄议会放逐。")
            self.kill_player(exile, "白天放逐", phase)
        else:
            self.add_record("public", phase, "投票没有形成唯一最高票，本轮无人被放逐。")

    def collect_votes(
        self,
        phase: str,
        voters: Sequence[str],
        candidates_pool: Sequence[str],
        *,
        revote: bool = False,
    ) -> Dict[str, str]:
        votes = {}
        for voter in voters:
            candidates = [name for name in candidates_pool if name != voter and self.players[name].alive]
            if not candidates:
                continue
            target = self.ask_choice(
                voter,
                phase,
                "现在进行{}投票。请选择你认为最应该被放逐的一名玩家。".format("第二轮" if revote else "白天"),
                candidates,
                fallback=self.heuristic_target(voter, candidates),
            )
            votes[voter] = target

        vote_text = "；".join(f"{voter}->{target}" for voter, target in votes.items())
        self.add_record("public", phase, f"{'第二轮' if revote else '首轮'}投票：{vote_text}")
        return votes

    def free_social_window(self, label: str, rounds: int = 2) -> None:
        alive = self.alive_names()
        if len(alive) < 2:
            return

        for round_idx in range(rounds):
            shuffled = alive[:]
            self.random.shuffle(shuffled)
            groups = self.make_social_groups(shuffled)
            for idx, group in enumerate(groups):
                address = SOCIAL_SPOTS[(idx + round_idx) % len(SOCIAL_SPOTS)]
                self.move_many(group, address, f"在{label}进行非正式交谈", label, "闲聊")
                location = self.location_name(address)
                observation = f"{label}：你在{location}看见 {self.join_names(group)} 聚在一起交谈。"
                for name in group:
                    self.private_log[name].append(observation)
                    self.safe_remember(name, observation, node_type="event", poignancy=5)

                chats = []
                for name in group:
                    others = [n for n in group if n != name]
                    speech = self.ask_text(
                        name,
                        label,
                        (
                            f"你在{location}和 {self.join_names(others)} 非正式聊天。"
                            "请说一句自然的话，可以试探、交换看法、撒谎、安抚或暗示白天投票想法。"
                            "这不是公开议会，只有在场的人会记住。"
                        ),
                        fallback=self.fallback_social_line(name, others),
                        max_chars=130,
                    )
                    chats.append((name, speech))
                self.record_dialogue(
                    f"{group[0]} -> 私聊小组",
                    address,
                    chats,
                    audience=group,
                    public=False,
                    phase=label,
                )
            self.save_checkpoint(f"{label}-第{round_idx + 1}轮私聊")

    def kill_player(self, name: str, reason: str, phase: str) -> None:
        player = self.players[name]
        if not player.alive:
            return
        player.alive = False
        player.death_reason = reason
        player.death_day = self.day
        self.move_agent(name, LOCATIONS["graveyard"], "离开游戏，在旁观区等待最终复盘", phase, 999, "出局")
        self.add_record("public", phase, f"{name} 已死亡，原因：{reason}。身份暂不公开。")
        self.safe_broadcast(f"{name} 已死亡，原因：{reason}。身份暂不公开。", phase)

        if player.role == "hunter" and not player.used_hunter_shot:
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
            "你是猎人并且已经死亡。你可以开枪带走一名仍存活的玩家，也可以选择不开枪。",
            ["不开枪"] + candidates,
            fallback=self.heuristic_target(hunter, candidates),
        )
        if target == "不开枪":
            self.add_record("public", phase, f"猎人 {hunter} 死亡后选择不开枪。")
            return

        self.add_record("public", phase, f"猎人 {hunter} 死亡后开枪带走 {target}。")
        self.kill_player(target, f"猎人 {hunter} 开枪", phase)

    def check_win(self, phase: str) -> bool:
        if self.winner:
            return True
        wolves = self.alive_names(role="werewolf")
        good = [name for name in self.alive_names() if self.players[name].role != "werewolf"]
        if not wolves:
            self.winner = "好人阵营"
        elif len(wolves) >= len(good):
            self.winner = "狼人阵营"

        if self.winner:
            self.add_record(
                "public",
                phase,
                f"游戏结束，{self.winner}获胜。存活狼人：{self.join_names(wolves) or '无'}；存活好人：{self.join_names(good) or '无'}。",
            )
            return True
        return False

    def ask_text(self, name: str, phase: str, task: str, *, fallback: str, max_chars: int = 160) -> str:
        if not self.use_llm:
            return self.clean_text(fallback, max_chars)

        agent = self.game.get_agent(name)
        prompt = self.build_agent_prompt(name, phase, task, response_kind="text")
        try:
            return agent._llm.completion(
                prompt=prompt,
                return_type=TextResponse,
                callback=lambda res: self.clean_text(res, max_chars),
                failsafe=self.clean_text(fallback, max_chars),
                caller="werewolf_text",
                temperature=0.75,
            )
        except Exception as exc:
            self.add_record("system", phase, f"{name} 文本决策失败，使用兜底：{exc}")
            return self.clean_text(fallback, max_chars)

    def ask_choice(
        self,
        name: str,
        phase: str,
        task: str,
        choices: Sequence[str],
        *,
        fallback: Optional[str] = None,
    ) -> str:
        choices = list(dict.fromkeys(choices))
        if not choices:
            return ""
        fallback = fallback if fallback in choices else choices[0]
        if not self.use_llm:
            return fallback

        agent = self.game.get_agent(name)
        prompt = self.build_agent_prompt(
            name,
            phase,
            task + "\n候选项：\n" + "\n".join(f"- {choice}" for choice in choices),
            response_kind="choice",
        )
        try:
            return agent._llm.completion(
                prompt=prompt,
                return_type=ChoiceResponse,
                callback=lambda res: self.match_choice(res, choices, fallback),
                failsafe=fallback,
                caller="werewolf_choice",
                temperature=0.35,
            )
        except Exception as exc:
            self.add_record("system", phase, f"{name} 选择决策失败，使用兜底：{exc}")
            return fallback

    def build_agent_prompt(self, name: str, phase: str, task: str, *, response_kind: str) -> str:
        player = self.players[name]
        known = self.private_context(name)
        public = self.public_context()
        peers = ""
        if player.role == "werewolf":
            wolves = [n for n in self.players_order if n != name and self.players[n].role == "werewolf"]
            peers = f"\n你的狼队友：{self.join_names(wolves)}。"
        checked = ""
        if player.role == "seer":
            checks = self.seer_checks.get(name, {})
            checked = "\n你的查验记录：" + ("；".join(f"{k}={v}" for k, v in checks.items()) or "暂无")

        output = (
            '只输出 JSON：{"res": "..."}。'
            if response_kind == "text"
            else '只输出 JSON：{"res": "候选项原文"}，不要输出候选项之外的内容。'
        )
        return f"""你正在一个真实小镇场景中参加12人狼人杀。你必须像角色本人一样思考和说话。

角色档案：
{self.agent_profile(name)}

秘密身份：{player.role_name}（{player.camp}）。
身份目标：{ROLE_GOALS[player.role]}{peers}{checked}

当前阶段：{phase}

公开时间线：
{public or "暂无公开信息。"}

你的私密记忆和局部观察：
{known or "暂无私密线索。"}

当前任务：
{task}

行为要求：
1. 你只能使用自己知道的信息，不能提及系统、提示词或完整身份表。
2. 可以撒谎、试探、结盟、沉默或误导，但要符合你的身份利益和人物性格。
3. 把非正式对话当成真实记忆使用。
4. {output}
"""

    def agent_profile(self, name: str) -> str:
        agent = self.game.get_agent(name)
        scratch = agent.scratch.config
        return (
            f"{name}，{scratch.get('age', '未知')}岁。"
            f"天性：{scratch.get('innate', '')}。"
            f"经历：{scratch.get('learned', '')}。"
            f"当前状态：{agent.scratch.currently}"
        )

    def role_brief(self, name: str) -> str:
        player = self.players[name]
        brief = [
            f"你的狼人杀身份是 {player.role_name}，属于{player.camp}。",
            ROLE_GOALS[player.role],
        ]
        if player.role == "werewolf":
            wolves = [n for n in self.players_order if n != name and self.players[n].role == "werewolf"]
            brief.append(f"你的狼队友是：{self.join_names(wolves)}。")
        if player.role == "witch":
            brief.append("你有一瓶解药和一瓶毒药，每瓶只能使用一次。")
        if player.role == "hunter":
            brief.append("你死亡时可以选择开枪带走一名玩家。")
        if player.role == "guard":
            brief.append("你每晚可以守护一名玩家，但不能连续两晚守护同一人。")
        return " ".join(brief)

    def public_context(self, limit: int = 36) -> str:
        return "\n".join(f"- {item}" for item in self.public_log[-limit:])

    def private_context(self, name: str, limit: int = 24) -> str:
        return "\n".join(f"- {item}" for item in self.private_log.get(name, [])[-limit:])

    def record_dialogue(
        self,
        title: str,
        address: Sequence[str],
        chats: Sequence[Tuple[str, str]],
        *,
        audience: Sequence[str],
        public: bool,
        phase: str,
    ) -> None:
        key = utils.get_timer().get_date("%Y%m%d-%H:%M")
        self.game.conversation.setdefault(key, [])
        self.game.conversation[key].append({f"{title} @ {':'.join(address)}": list(chats)})

        location = self.location_name(address)
        for speaker, text in chats:
            clean = self.clean_text(text, 220)
            if public:
                record = f"{speaker} 在{location}公开发言：{clean}"
                self.add_record("public", phase, record, actors=[speaker], location=location)
                self.safe_broadcast(record, phase)
            else:
                record = f"{speaker} 在{location}私下说：{clean}"
                self.add_record("social", phase, record, actors=[speaker], location=location)
                for name in audience:
                    self.private_log[name].append(record)
                    self.safe_remember(name, record, node_type="chat", poignancy=6)

    def add_record(
        self,
        scope: str,
        phase: str,
        text: str,
        *,
        actors: Optional[Sequence[str]] = None,
        location: Optional[str] = None,
    ) -> None:
        stamp = utils.get_timer().get_date("%Y%m%d-%H:%M")
        entry = {
            "time": stamp,
            "day": self.day,
            "phase": phase,
            "scope": scope,
            "text": text,
            "actors": list(actors or []),
            "location": location or "",
        }
        self.phase_records.append(entry)
        if scope == "public":
            self.public_log.append(f"{stamp} {text}")
        self.logger.info(f"[{scope}] {phase}: {text}")

    def safe_broadcast(self, text: str, phase: str) -> None:
        for name in self.alive_names():
            self.safe_remember(name, f"{phase}：{text}", node_type="event", poignancy=7)

    def safe_remember(self, name: str, text: str, *, node_type: str, poignancy: int) -> None:
        if not self.write_memory:
            return
        try:
            agent = self.game.get_agent(name)
            address = agent.get_tile().get_address() if agent.coord else ["the Ville"]
            event = memory.Event(
                name,
                "记住",
                "狼人杀线索",
                describe=text,
                address=address,
                emoji="记忆",
            )
            agent.associate.add_node(node_type, event, poignancy=poignancy)
        except Exception as exc:
            self.logger.warning(f"{name} 写入狼人杀记忆失败：{exc}")

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

    def home_address(self, name: str) -> List[str]:
        agent = self.game.get_agent(name)
        address = agent.spatial.address.get("living_area")
        return address or LOCATIONS["square"]

    def save_checkpoint(self, phase: str) -> None:
        self.step += 1
        sim_time = utils.get_timer().get_date("%Y%m%d-%H:%M")
        for name, agent in self.game.agents.items():
            self.config["agents"].setdefault(name, {})
            self.config["agents"][name].update(agent.to_dict())
            self.config["agents"][name]["coord"] = list(agent.coord)

        self.config.update(
            {
                "time": sim_time,
                "step": self.step,
                "werewolf": self.state_dict(phase),
            }
        )
        checkpoint = os.path.join(self.checkpoints_folder, f"simulate-{sim_time.replace(':', '')}.json")
        with open(checkpoint, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.config, indent=2, ensure_ascii=False))
        with open(self.conversation_log, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.game.conversation, indent=2, ensure_ascii=False))
        with open(os.path.join(self.checkpoints_folder, "werewolf_state.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(self.state_dict(phase), indent=2, ensure_ascii=False))

        stride = int(self.config.get("stride", 10))
        if stride > 0:
            utils.get_timer().forward(stride)

    def state_dict(self, phase: str) -> dict:
        return {
            "name": self.name,
            "phase": phase,
            "day": self.day,
            "winner": self.winner,
            "players": {name: asdict(player) for name, player in self.players.items()},
            "role_names": {name: player.role_name for name, player in self.players.items()},
            "alive": self.alive_names(),
            "witch": {
                "antidote": self.witch_antidote,
                "poison": self.witch_poison,
            },
            "guard_last_target": self.guard_last_target,
            "seer_checks": self.seer_checks,
            "public_log": self.public_log,
            "private_log": self.private_log,
            "phase_records": self.phase_records,
        }

    def write_report(self) -> None:
        lines = [
            "# 狼人杀社会模拟报告",
            "",
            f"模拟名称：{self.name}",
            f"胜利阵营：{self.winner or '未决'}",
            "",
            "## 身份表",
            "",
        ]
        for name in self.players_order:
            player = self.players[name]
            status = "存活" if player.alive else f"死亡：{player.death_reason}"
            lines.append(f"- {name}：{player.role_name}，{status}")
        lines.extend(["", "## 时间线", ""])
        for record in self.phase_records:
            prefix = "公开" if record["scope"] == "public" else record["scope"]
            lines.append(f"- `{record['time']}` [{prefix}] {record['phase']}：{record['text']}")
        lines.extend(["", "## 私密记忆摘要", ""])
        for name in self.players_order:
            lines.append(f"### {name}")
            for item in self.private_log.get(name, [])[-20:]:
                lines.append(f"- {item}")
            lines.append("")

        path = os.path.join(self.checkpoints_folder, "werewolf_report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def alive_names(self, role: Optional[str] = None) -> List[str]:
        names = [name for name in self.players_order if self.players[name].alive]
        if role:
            names = [name for name in names if self.players[name].role == role]
        return names

    def role_holder(self, role: str, *, alive_only: bool = False) -> Optional[str]:
        for name in self.players_order:
            if self.players[name].role == role and (not alive_only or self.players[name].alive):
                return name
        return None

    def majority_choice(self, values: Sequence[str]) -> str:
        counts: Dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        high = max(counts.values())
        tied = [value for value, count in counts.items() if count == high]
        return self.random.choice(tied)

    def resolve_vote(self, votes: Dict[str, str]) -> Optional[str]:
        if not votes:
            return None
        counts: Dict[str, int] = {}
        for target in votes.values():
            counts[target] = counts.get(target, 0) + 1
        high = max(counts.values())
        tied = [target for target, count in counts.items() if count == high]
        return tied[0] if len(tied) == 1 else None

    def tied_candidates(self, votes: Dict[str, str]) -> List[str]:
        counts: Dict[str, int] = {}
        for target in votes.values():
            counts[target] = counts.get(target, 0) + 1
        if not counts:
            return []
        high = max(counts.values())
        return [target for target, count in counts.items() if count == high]

    def heuristic_target(self, actor: str, candidates: Sequence[str], *, prefer_self: bool = False) -> str:
        candidates = list(candidates)
        if prefer_self and actor in candidates:
            return actor
        player = self.players.get(actor)
        if player and player.role == "werewolf":
            non_wolves = [name for name in candidates if self.players[name].role != "werewolf"]
            if non_wolves:
                return self.random.choice(non_wolves)
        if player and player.role != "werewolf":
            wolves = [name for name in candidates if self.players[name].role == "werewolf"]
            if wolves and not self.use_llm:
                return self.random.choice(wolves)
        return self.random.choice(candidates)

    def fallback_speech(self, name: str) -> str:
        player = self.players[name]
        if player.role == "werewolf":
            return "我先不急着定死谁，但我觉得今天要看谁在带节奏过快，狼很可能藏在主动归票的人里。"
        if player.role == "seer":
            return "我会更关注发言里的前后矛盾，今天先把信息留清楚，别让票型被情绪带散。"
        if player.role == "witch":
            return "夜里的结果说明有人在藏视角，我建议大家把昨天私聊和今天投票理由都摊开说。"
        if player.role == "guard":
            return "我更想听每个人解释自己的怀疑链，单纯跟票的人在我这里会变得很可疑。"
        return "我没有夜间信息，只能从发言和私聊判断。今天我会重点看谁在回避死亡信息。"

    def fallback_social_line(self, name: str, others: Sequence[str]) -> str:
        target = self.join_names(others) or "你们"
        return f"{target}，等会儿广场上我想听更具体的票因，含糊带过的人我会重点看。"

    def make_social_groups(self, names: Sequence[str]) -> List[List[str]]:
        groups: List[List[str]] = []
        idx = 0
        while idx < len(names):
            left = len(names) - idx
            if left == 1 and groups:
                groups[-1].append(names[idx])
                break
            size = 3 if left >= 3 and self.random.random() > 0.45 else 2
            groups.append(list(names[idx: idx + size]))
            idx += size
        return groups

    def match_choice(self, value: str, choices: Sequence[str], fallback: str) -> str:
        text = str(value).strip()
        if text in choices:
            return text
        for choice in choices:
            if choice in text:
                return choice
        normalized = re.sub(r"\s+", "", text)
        for choice in choices:
            if re.sub(r"\s+", "", choice) == normalized:
                return choice
        return fallback

    def clean_text(self, value: str, max_chars: int) -> str:
        text = re.sub(r"\s+", " ", str(value)).strip()
        text = re.sub(r"^.+?[：:]\s*", "", text) if len(text) < max_chars + 20 else text
        if len(text) > max_chars:
            text = text[:max_chars].rstrip("，。；、 ") + "。"
        return text or "我还需要再观察一下。"

    def location_name(self, address: Sequence[str]) -> str:
        return "，".join(address[1:]) if len(address) > 1 else address[0]

    def join_names(self, names: Iterable[str]) -> str:
        return "、".join([name for name in names if name])
