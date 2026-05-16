# 文件作用：并行采集 RL 训练数据。
# 单 cycle 流程：
#   for role in roles:
#     for g in range(groups_per_role):
#       生成 group_size 个 game seed
#       异步起 group_size 局并行（线程池），同身份 + 同座位
#       每局跑完 → 抽 Qwen 那一座位的 trajectory steps → 累计 reward
#       打包 GroupRecord 进 ReplayBuffer

import copy
import os
import random
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, List, Optional, Sequence

from modules.rl.buffer import (
    GroupRecord, ReplayBuffer, compute_total_reward_for_qwen, extract_qwen_steps,
)
from modules.rl.config import RLConfig
from modules.werewolf.director import (
    DEFAULT_WEREWOLF_PLAYERS, WerewolfDirector,
    build_werewolf_config, load_agent_base,
)
from modules.werewolf.rules import ROLE_DECK


def _make_role_map(
    rng: random.Random,
    players: Sequence[str],
    qwen_seat: str,
    qwen_role: str,
) -> Dict[str, str]:
    """生成一个固定身份分配：Qwen 座位锁定为指定 role，其余按 ROLE_DECK 随机洗。"""
    deck = list(ROLE_DECK)
    deck.remove(qwen_role)  # Qwen 占走一份
    rng.shuffle(deck)
    role_map = {qwen_seat: qwen_role}
    other_seats = [p for p in players if p != qwen_seat]
    for seat, role in zip(other_seats, deck):
        role_map[seat] = role
    return role_map


def _override_qwen_seat_provider(config: dict, qwen_seat: str, qwen_provider_cfg: dict) -> dict:
    """让 qwen_seat 那一名 agent 使用 vllm 本地 model；其他保持 agent_base 配置。"""
    config = copy.deepcopy(config)
    seat_cfg = config["agents"].setdefault(qwen_seat, {})
    # 注入到 agent.json 加载后的合并配置；agent_base["think"]["llm"] 是默认，这里用 agent 级覆盖
    seat_cfg["think"] = {"llm": qwen_provider_cfg}
    return config


def _run_one_game(
    *, game_id: str, qwen_seat: str, qwen_role: str,
    seed: int, scene_mode: str, players: List[str],
    base_config: dict, qwen_provider_cfg: dict, role_map: Dict[str, str],
    use_llm: bool = True,
) -> Dict:
    """同步跑一局，返回 dict（含 Qwen steps + winner）。线程入口。"""
    config = _override_qwen_seat_provider(base_config, qwen_seat, qwen_provider_cfg)
    director = WerewolfDirector(
        name=game_id,
        static_root="frontend/static",
        checkpoints_folder=os.path.join("results", "checkpoints", game_id),
        config=config,
        seed=seed,
        role_map=role_map,
        use_llm=use_llm,
        write_memory=False,
        scene_mode=scene_mode,
    )
    try:
        state = director.run()
        qwen_steps = extract_qwen_steps(director.trajectories, qwen_seat)
        return {
            "qwen_steps": qwen_steps,
            "winner": state.get("winner"),
            "role_map": role_map,
        }
    finally:
        director.dispose()


class RLCollector:
    """协调一个 cycle 的并行采集。"""

    def __init__(self, cfg: RLConfig, players: Optional[List[str]] = None, agent_base: Optional[dict] = None):
        self.cfg = cfg
        self.players = list(players or DEFAULT_WEREWOLF_PLAYERS)
        self.agent_base = agent_base or load_agent_base()
        # 准备 vllm provider 配置块（覆盖到 Qwen 座位）
        self.qwen_provider_cfg = {
            "provider": cfg.qwen_seat_provider,
            "model": cfg.base_model,
            "base_url": cfg.vllm_endpoint,
            "api_key": "EMPTY",
        }
        self.base_config = build_werewolf_config(
            start_time="20240213-18:00",
            stride=10,
            players=self.players,
            agent_base=self.agent_base,
        )
        self.base_config["agent_base"]["associate"] = {"disabled": True}
        self.seat_pool = list(cfg.seat_pool) if cfg.seat_pool else self.players[:]

    # ─── 单 group 采集 ───────────────────────────────────────────
    def collect_group(self, cycle: int, role: str, group_idx: int) -> GroupRecord:
        rng = random.Random(self.cfg.seed_base + cycle * 100000 + group_idx * 100)
        qwen_seat = rng.choice(self.seat_pool)
        role_map = _make_role_map(rng, self.players, qwen_seat, role)

        # 起 group_size 个 future
        futures: List[Future] = []
        ex = ThreadPoolExecutor(max_workers=min(self.cfg.collection_workers, self.cfg.group_size))
        try:
            for i in range(self.cfg.group_size):
                game_id = f"cyc{cycle}_grp{group_idx}_{role}_{qwen_seat}_g{i}"
                seed = self.cfg.seed_base + cycle * 100000 + group_idx * 100 + i
                fut = ex.submit(
                    _run_one_game,
                    game_id=game_id, qwen_seat=qwen_seat, qwen_role=role,
                    seed=seed, scene_mode=self.cfg.scene_mode,
                    players=self.players, base_config=self.base_config,
                    qwen_provider_cfg=self.qwen_provider_cfg, role_map=role_map,
                    use_llm=self.cfg.use_llm,
                )
                futures.append(fut)
            results = [f.result() for f in futures]
        finally:
            ex.shutdown(wait=True)

        # 算每局 reward + 打包 GroupRecord
        shaping = {
            "format_ok": self.cfg.reward_format,
            "mentions_player": self.cfg.reward_mention,
            "cites_event": self.cfg.reward_cite,
        }
        rewards = []
        steps_per_game = []
        for r in results:
            qwen_steps = r["qwen_steps"]
            tot = compute_total_reward_for_qwen(
                qwen_steps, win_bonus_weight=self.cfg.reward_episode,
                shaping_weights=shaping,
            )
            rewards.append(tot)
            steps_per_game.append(qwen_steps)
        return GroupRecord(
            role=role, seat=qwen_seat,
            rewards=rewards, qwen_steps_per_game=steps_per_game,
            cycle=cycle,
            meta={"role_map": results[0]["role_map"], "winners": [r["winner"] for r in results]},
        )

    # ─── 整 cycle 采集 ───────────────────────────────────────────
    def collect_cycle(self, cycle: int) -> ReplayBuffer:
        buf = ReplayBuffer()
        for role in self.cfg.roles:
            for g in range(self.cfg.groups_per_role):
                group = self.collect_group(cycle, role, g)
                buf.push(group)
        return buf
