# 文件作用：GRPO 训练用 Buffer + GroupRecord 数据结构。
# 一个 GroupRecord = 同 role/seat 下并行 N 局产生的 trajectory 集合；advantage 在 group 内归一。

import json
import math
import os
import random
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterator, List, Optional

from modules.werewolf.trajectory import TrajectoryStep


@dataclass
class GroupRecord:
    """同 role/seat 下并行 N 局产生的 trajectory 集合。"""
    role: str                                  # Qwen 在这一 group 扮演的身份
    seat: str                                  # Qwen 在这一 group 占的座位
    rewards: List[float]                       # 长度 == group_size，每局一个累计 reward
    qwen_steps_per_game: List[List[dict]]      # 每局 Qwen 那一座位的 trajectory step 列表（dict）
    cycle: int = 0
    meta: Dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.rewards)

    def advantages(self, normalize: bool = True) -> List[float]:
        """group 内 (R - mean) / std。若全相等 advantage 全 0（本 group 无学习信号）。"""
        if not self.rewards:
            return []
        mean = sum(self.rewards) / len(self.rewards)
        if not normalize:
            return [r - mean for r in self.rewards]
        var = sum((r - mean) ** 2 for r in self.rewards) / len(self.rewards)
        std = math.sqrt(var)
        if std < 1e-8:
            return [0.0] * len(self.rewards)
        return [(r - mean) / std for r in self.rewards]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReplayBuffer:
    """一轮 cycle 内采到的所有 GroupRecord。"""
    groups: List[GroupRecord] = field(default_factory=list)

    def push(self, group: GroupRecord) -> None:
        self.groups.append(group)

    def extend(self, groups: List[GroupRecord]) -> None:
        self.groups.extend(groups)

    def clear(self) -> None:
        self.groups.clear()

    def __len__(self) -> int:
        return len(self.groups)

    def shuffled(self, rng: Optional[random.Random] = None) -> List[GroupRecord]:
        """返回打乱后的副本（不改原 groups）。"""
        out = list(self.groups)
        (rng or random).shuffle(out)
        return out

    def iter_steps_with_advantage(self, normalize: bool = True) -> Iterator[Dict]:
        """逐 step 迭代，每条带 group advantage（用于喂训练器）。
        yield: {"step": dict, "advantage": float, "role": str, "seat": str, "cycle": int, "group_idx": int}
        """
        for group in self.groups:
            advs = group.advantages(normalize=normalize)
            for game_idx, (steps, adv) in enumerate(zip(group.qwen_steps_per_game, advs)):
                for step in steps:
                    yield {
                        "step": step,
                        "advantage": float(adv),
                        "role": group.role,
                        "seat": group.seat,
                        "cycle": group.cycle,
                        "group_idx": game_idx,
                    }

    def stats(self) -> dict:
        """简要统计，用于训练监控（reward 分布、有效 group 数等）。"""
        n_total = len(self.groups)
        rewards_flat = [r for g in self.groups for r in g.rewards]
        if not rewards_flat:
            return {"groups": 0, "rewards": [], "zero_variance_groups": 0}
        n_zero_var = sum(
            1 for g in self.groups
            if g.size >= 2 and max(g.rewards) - min(g.rewards) < 1e-8
        )
        by_role: Dict[str, List[float]] = {}
        for g in self.groups:
            by_role.setdefault(g.role, []).extend(g.rewards)
        return {
            "groups": n_total,
            "total_steps": sum(
                len(s) for g in self.groups for s in g.qwen_steps_per_game
            ),
            "reward_mean": sum(rewards_flat) / len(rewards_flat),
            "reward_min": min(rewards_flat),
            "reward_max": max(rewards_flat),
            "zero_variance_groups": n_zero_var,
            "rewards_by_role": {
                role: {"mean": sum(rs) / len(rs), "count": len(rs)}
                for role, rs in by_role.items()
            },
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"groups": [g.to_dict() for g in self.groups]},
                f, ensure_ascii=False, indent=2,
            )

    @classmethod
    def load(cls, path: str) -> "ReplayBuffer":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        groups = [GroupRecord(**g) for g in data.get("groups", [])]
        return cls(groups=groups)


# =========================================================================
# 帮助函数：从 director.trajectories 提取 Qwen 那一座位的 steps
# =========================================================================
def extract_qwen_steps(trajectories_dict_or_recorder, qwen_seat: str) -> List[dict]:
    """从 TrajectoryRecorder（或它 to_dict 后的 {steps: [...]}）抽出 qwen_seat 的全部 step。"""
    if hasattr(trajectories_dict_or_recorder, "all_for"):
        return [s.to_dict() for s in trajectories_dict_or_recorder.all_for(qwen_seat)]
    steps = trajectories_dict_or_recorder.get("steps", [])
    return [s for s in steps if s.get("agent") == qwen_seat]


def compute_total_reward_for_qwen(
    qwen_steps: List[dict],
    win_bonus_weight: float,
    shaping_weights: Optional[Dict[str, float]] = None,
) -> float:
    """累计单局 Qwen 的 reward：sum(step_reward) + sum(shaping) + win_bonus * episode_reward。

    shaping_weights：{"format": w, "mention": w, "cite": w}；
    每 step 的 obs 里若已带 format_ok / mentions_player / cites_event 布尔字段，对应加权。
    """
    shaping_weights = shaping_weights or {}
    total = 0.0
    for s in qwen_steps:
        total += float(s.get("reward_step", 0.0))
        obs = s.get("obs") or {}
        for key, w in shaping_weights.items():
            if obs.get(key):
                total += w
    if qwen_steps:
        total += win_bonus_weight * float(qwen_steps[-1].get("reward_episode", 0.0))
    return total
