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
import threading
from typing import Dict, Iterable, List, Optional, Sequence

from modules import memory, utils
from modules.game import GameRegistry, create_game
from modules.utils import ActiveGameContext

from modules.werewolf.locations import (
    LOCATIONS,
    SOCIAL_SPOTS,
    SOCIAL_SPOT_KEYS,
    location_display_from_address,
    shichen,
)
from modules.werewolf.player import WerewolfPlayer, role_brief as _role_brief
from modules.werewolf.rules import (
    PLAYER_PERSONALITIES,
    ROLE_DECK,
    SAFETY_DAY_LIMIT,
    check_winner,
    majority_choice as _majority_choice,
)
from modules.werewolf.text_utils import clean_text as _clean_text, join_names as _join_names
from modules.werewolf import recorder as _recorder
from modules.prompt import HUNTER_SHOT_TASK
from modules.werewolf import llm_io as _llm_io
from modules.werewolf.phases import night as _night, day as _day, social as _social
from modules.werewolf.beliefs import BeliefState, init_for as _init_belief
from modules.werewolf.llm_judge import update_belief_via_llm
from modules.werewolf.trajectory import TrajectoryRecorder, snapshot_belief
from modules.werewolf import reward as _reward


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
        scene_mode: str = "social",
        logger=None,
    ):
        """scene_mode:
          - "social"（默认）：完整江南叙事，含开场社交/辩论/申时余韵/NPC 流言
          - "game"：v1 纯狼人杀，跳开场社交、跳申时余韵、辩论压缩到 2 轮、禁用流言、prompt 用中性文案
        """
        if scene_mode not in ("social", "game"):
            raise ValueError(f"scene_mode 必须是 'social' 或 'game'，收到：{scene_mode}")
        self.scene_mode = scene_mode

        self.name = name
        self.static_root = static_root
        self.checkpoints_folder = checkpoints_folder
        self.config = config
        self.random = random.Random(seed)
        self.role_map = role_map
        self.use_llm = use_llm
        self.write_memory = write_memory
        # game 模式辩论缩到 2 轮（除非外部显式指定）
        self.debate_turns = 2 if scene_mode == "game" and debate_turns == 4 else debate_turns
        self.logger = logger or utils.create_io_logger("info")

        os.makedirs(checkpoints_folder, exist_ok=True)
        self.conversation_log = os.path.join(checkpoints_folder, "conversation.json")
        if os.path.exists(self.conversation_log):
            with open(self.conversation_log, "r", encoding="utf-8") as f:
                conversation = json.load(f)
        else:
            conversation = {}

        # 按 name 创建并注册到 GameRegistry；返回的 game 直接绑定到本 director，不再依赖全局 singleton。
        import time as _time
        _t0 = _time.perf_counter()
        self.game = create_game(name, static_root, config, conversation, logger=self.logger)
        _t1 = _time.perf_counter()
        print(f"[director.__init__] {name}: create_game (maze + 12 agents) {(_t1 - _t0)*1000:.0f}ms", flush=True)
        self.game.reset_game()
        _t2 = _time.perf_counter()
        print(f"[director.__init__] {name}: reset_game (12 × create_llm_model) {(_t2 - _t1)*1000:.0f}ms", flush=True)

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
        # NPC 流言：game 模式禁用（RL 训练不需要叙事噪声）
        self.gossip_mill = None
        if scene_mode == "social":
            try:
                from modules.gossip import GossipMill

                self.gossip_mill = GossipMill(self.random)
            except Exception as exc:
                self.logger.warning(f"流言模块未加载：{exc}")

        # RL 训练基础设施（路 3）
        self.belief_states: Dict[str, BeliefState] = {}
        self.trajectories = TrajectoryRecorder()
        # 阶段末扫描事件用的游标：每个 Agent 上次 belief 更新时 phase_records 已处理到的索引
        self._phase_record_cursor_per_agent: Dict[str, int] = {}
        # 每次 ask_text/ask_choice 后，model 把 prompt/text/logprobs 暂存到这里
        # 紧跟着的 record_trajectory() 自动消费并清空（防止下一次 ask 覆盖）
        self._last_capture: Optional[Dict] = None

    # =========================================================================
    # Scene 适配 helper（被 phases/* 调用）
    # =========================================================================
    def phase_label(self, day: int, slot: str) -> str:
        """根据当前 scene_mode 返回该阶段的展示名。
        slot ∈ {night, dawn, day_council, evening_pre, evening_post}。
        """
        from modules.prompt.dispatcher import phase_label as _phase_label
        return _phase_label(self.scene_mode, day, slot)

    def task(self, key: str, **kwargs) -> str:
        """根据当前 scene_mode 返回任意阶段的任务文案。"""
        from modules.prompt.dispatcher import get_task
        return get_task(self.scene_mode, key, **kwargs)

    # =========================================================================
    # 主循环
    # =========================================================================
    def run(self) -> dict:
        # 多线程并行时，确保本线程的活跃 game 是自己；老的 utils.get_timer() 等调用会自动落到 self.game.timer
        with ActiveGameContext.bind(self.game):
            return self._run_inner()

    def dispose(self) -> None:
        """跑完一局后释放：从 GameRegistry 删 + 清线程活跃位。
        并行 GRPO 采集时建议每局结束调用，避免内存累积。
        """
        try:
            GameRegistry.remove(self.name)
        except Exception:
            pass
        if ActiveGameContext.get() is self.game:
            ActiveGameContext.clear()

    def _run_inner(self) -> dict:
        self.setup()

        if self.scene_mode == "social":
            label = self.phase_label(0, "evening_pre")
            self.free_social_window(label, rounds=3)
            self.end_of_phase(label)

        for day in range(1, SAFETY_DAY_LIMIT + 1):
            self.day = day

            night_label = self.phase_label(day, "night")
            self.night_phase(day)
            self.end_of_phase(night_label)
            if self.check_win("夜晚结算"):
                break

            day_label = self.phase_label(day, "day_council")
            self.day_phase(day)
            self.end_of_phase(day_label)
            if self.check_win("白天议会"):
                break

            if self.scene_mode == "social":
                evening_label = self.phase_label(day, "evening_post")
                self.free_social_window(evening_label, rounds=2)
                self.end_of_phase(evening_label)

        if not self.winner:
            self.add_record(
                "public",
                "游戏结束",
                f"达到内部安全上限 {SAFETY_DAY_LIMIT} 天，游戏暂停。当前仍有 {len(self.alive_names())} 名玩家存活。",
            )

        self.fill_episode_rewards()
        self._save_trajectories()
        self.write_report()
        self.save_checkpoint("结束")
        return self.state_dict("结束")

    def _save_trajectories(self) -> None:
        """把 trajectory 单独存一份 JSON，方便 RL 训练直接消费。"""
        path = os.path.join(self.checkpoints_folder, "trajectories.json")
        try:
            self.trajectories.save(path)
        except Exception as exc:
            self.logger.warning(f"trajectories.json 写盘失败：{exc}")

    def setup(self) -> None:
        import time as _time
        _t0 = _time.perf_counter()

        self.assign_roles()
        _t1 = _time.perf_counter()
        print(f"[director.setup] {self.name}: assign_roles {(_t1 - _t0)*1000:.0f}ms", flush=True)

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
        _t2 = _time.perf_counter()
        print(f"[director.setup] {self.name}: move 12 agents + briefs {(_t2 - _t1)*1000:.0f}ms", flush=True)

        # 路 3：每个 Agent 形成初始 belief（按身份不同有不同先验）
        self.belief_states = {
            name: _init_belief(
                holder_name=name,
                holder_role=self.players[name].role,
                all_players=self.players_order,
                wolf_teammates=[
                    n for n in self.players_order
                    if n != name and self.players[n].role == "werewolf"
                ] if self.players[name].role == "werewolf" else (),
            )
            for name in self.players_order
        }
        self._phase_record_cursor_per_agent = {name: 0 for name in self.players_order}
        _t3 = _time.perf_counter()
        print(f"[director.setup] {self.name}: init 12 belief_states {(_t3 - _t2)*1000:.0f}ms", flush=True)

        opening_record = (
            "12 名玩家已收到身份牌。4 狼人 + 预言家 + 女巫 + 猎人 + 守卫 + 4 村民，"
            "白天议会发言投票，夜晚各方秘密行动，开始博弈。"
            if self.scene_mode == "game"
            else "江南古镇风云骤起。12 名镇民暗中收到身份牌，白日议政广场，黑夜各归其所，狼影潜行。"
        )
        self.add_record("public", "开局", opening_record)
        self.save_checkpoint("开局")
        _t4 = _time.perf_counter()
        print(f"[director.setup] {self.name}: save_checkpoint {(_t4 - _t3)*1000:.0f}ms", flush=True)

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
            personalities = PLAYER_PERSONALITIES[self.role_map[name]]
            picked = self.random.choice(personalities)
            self.players[name].personality_name = picked["name"]
            self.players[name].personality_description = picked["description"]

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
        if self.scene_mode == "game":
            move_desc = "被移出场，进入旁观区"
            death_announce = f"{name} 出局，原因：{reason}。身份暂不公开。"
        else:
            move_desc = "棺木抬出镇外，于乱葬岗等待最终复盘"
            death_announce = f"{name} 已殁，死因：{reason}。身份暂不公开。"
        self.move_agent(name, LOCATIONS["graveyard"], move_desc, phase, 999, "出局")
        self.add_record("public", phase, death_announce)
        self.safe_broadcast(death_announce, phase)

        if player.role == "hunter" and not player.used_hunter_shot:
            # 标准规则：被女巫毒药毒杀的猎人无法触发临死反扑
            if "女巫毒药" in reason:
                player.used_hunter_shot = True
                msg = (
                    f"{name} 被毒杀，猎人技能无效。"
                    if self.scene_mode == "game"
                    else f"{name} 七窍流毒，临死反扑之力尽失。"
                )
                self.add_record("public", phase, msg)
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
            self.task("hunter_shot"),
            ["不开枪"] + candidates,
            fallback=self.heuristic_target(hunter, candidates),
        )
        if target == "不开枪":
            msg = (
                f"猎人 {hunter} 放弃开枪。"
                if self.scene_mode == "game"
                else f"猎人 {hunter} 临死前放下了手。"
            )
            self.add_record("public", phase, msg)
            return

        msg = (
            f"猎人 {hunter} 开枪带走 {target}。"
            if self.scene_mode == "game"
            else f"猎人 {hunter} 临死反扑，带走 {target}。"
        )
        self.add_record("public", phase, msg)
        self.kill_player(target, f"猎人 {hunter} 开枪", phase)

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
        return location_display_from_address(address, mode=self.scene_mode)

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

    # =========================================================================
    # 路 3：belief + trajectory + reward
    # =========================================================================
    def belief_of(self, name: str) -> Optional[BeliefState]:
        return self.belief_states.get(name)

    def end_of_phase(self, phase_label: str) -> None:
        """阶段末批量更新 belief、计算 step reward、回填到 trajectory。

        中颗粒度（每阶段末，每存活听众调用一次 LLM）。
        """
        if not self.belief_states:
            return

        alive = self.alive_names()
        print(f"[T-{threading.current_thread().name}] end_of_phase {phase_label}: {len(alive)} survivors, "
              f"updating beliefs...", flush=True)

        # 1. 取本阶段新增的 public/secret/social 事件（按 holder 可见性筛选）
        records = self.phase_records
        cursor = self._phase_record_cursor_per_agent

        # 2. 备份 prior（深拷贝），用于 reward 计算
        prior = {n: BeliefState(holder=n, beliefs=dict(b.beliefs), locked=dict(b.locked))
                 for n, b in self.belief_states.items()}

        # 3. 对每个存活 Agent 调一次 LLM 重估
        real_roles = {n: p.role for n, p in self.players.items()}
        for idx, name in enumerate(alive):
            visible = self._visible_events_for(name, records, cursor.get(name, 0))
            if not visible:
                continue
            print(f"[{self.name}]   belief {idx + 1}/{len(alive)}: {name} ({real_roles[name]})",
                  flush=True)
            new_belief = update_belief_via_llm(
                self,
                witness_name=name,
                prior=prior[name],
                phase_label=phase_label,
                new_events=visible,
            )
            self.belief_states[name] = new_belief
        print(f"[T-{threading.current_thread().name}] end_of_phase {phase_label}: done", flush=True)
        # 4. 全员（无论活死）游标推进
        for name in self.players_order:
            cursor[name] = len(records)

        # 5. 给本阶段内每条 trajectory step 计算 step_reward
        for step in self.trajectories.steps_in_phase(phase_label):
            if step.reward_step != 0.0:
                continue  # 已填过
            actor = step.agent
            actor_role = real_roles.get(actor, "")
            if step.decision_type == "speech":
                step.reward_step = _reward.step_reward_for_speech(
                    actor, actor_role, prior, self.belief_states, real_roles, self.alive_names()
                )
            elif step.decision_type == "vote":
                step.reward_step = _reward.step_reward_for_vote(
                    actor, actor_role, str(step.action), real_roles
                )
            elif step.decision_type == "skill":
                skill = step.obs.get("skill", "")
                target = step.action if isinstance(step.action, str) else None
                step.reward_step = _reward.step_reward_for_skill(
                    actor_role, skill, target, real_roles
                )

    def _visible_events_for(self, holder: str, records: List[dict], from_idx: int) -> List[str]:
        """从 phase_records 切出 holder 可见的那些事件文本。"""
        out: List[str] = []
        for rec in records[from_idx:]:
            scope = rec.get("scope")
            text = rec.get("text", "")
            actors = rec.get("actors") or []
            if scope == "public" or scope == "movement":
                out.append(text)
            elif scope == "social":
                # 只对参与者可见——保险起见用 actors 字段近似
                if holder in actors:
                    out.append(text)
            # secret 不向其他人广播，只对 actor 自己可见
            elif scope == "secret":
                if holder in actors:
                    out.append(text)
            # system 不进 belief 更新
        return out

    def fill_episode_rewards(self) -> None:
        """局末：把 reward_episode 填到每条 trajectory step。"""
        if not self.winner or not self.trajectories.steps:
            return
        ep_rewards = {
            name: _reward.episode_reward(self.winner, p.role)
            for name, p in self.players.items()
        }
        self.trajectories.fill_episode_reward(ep_rewards)

    def capture_last(self, agent_name: str) -> None:
        """ask_text / ask_choice 调用结束后立即调用，把模型的 last_call 暂存到本 director。
        紧跟着的 record_trajectory() 会消费这份数据并清空。
        若 model 没产出 logprob（OpenAI API 等），仍能拿到 prompt 和 text。
        """
        try:
            agent = self.game.get_agent(agent_name)
            self._last_capture = getattr(agent._llm, "last_call", None)
        except Exception:
            self._last_capture = None

    def record_trajectory(
        self,
        agent: str,
        phase: str,
        decision_type: str,
        action,
        candidates: Optional[List[str]] = None,
        extra_obs: Optional[Dict] = None,
    ) -> None:
        """phase 模块统一通过此入口写 trajectory。
        如果有暂存的 _last_capture（紧跟在 ask_* 后），自动把 prompt / logprobs / tokens 填进 step。
        """
        obs = {
            "my_role": self.players[agent].role if agent in self.players else "",
            "my_belief": snapshot_belief(self.belief_states.get(agent)),
            "public_log_tail": self.public_log[-20:],
            "private_log_tail": self.private_log.get(agent, [])[-12:],
            "alive": self.alive_names(),
            "day": self.day,
        }
        if extra_obs:
            obs.update(extra_obs)
        step = self.trajectories.record(
            agent=agent,
            phase=phase,
            day=self.day,
            decision_type=decision_type,
            obs=obs,
            action=action,
            candidates=candidates,
        )
        # 消费 capture buffer
        if self._last_capture:
            step.prompt = self._last_capture.get("prompt")
            step.logprobs = self._last_capture.get("logprobs")
            step.tokens = self._last_capture.get("tokens")
            self._last_capture = None
