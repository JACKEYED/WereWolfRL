# 文件作用：决策点 trajectory 收集器。
# 每次 Agent 做决策（发言 / 投票 / 技能）→ 写一条 TrajectoryStep。
# 阶段末 / 局末 → 回填 step / episode reward。
# 这是 RL 训练（SFT / DPO / PPO / GRPO）直接消费的数据格式。

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from modules.werewolf.beliefs import BeliefState


@dataclass
class TrajectoryStep:
    """单个决策点。"""
    step_id: int
    agent: str
    phase: str
    day: int
    decision_type: str  # 'speech' / 'vote' / 'skill' / 'choice'
    obs: Dict[str, Any] = field(default_factory=dict)  # 决策前的状态快照
    candidates: Optional[List[str]] = None  # 选择题候选；自由文本时为 None
    action: Any = None  # 文本 / 选择项 / 结构化字段
    reward_step: float = 0.0  # 阶段末填
    reward_episode: float = 0.0  # 局末填
    # RL 训练必需：rollout 时 actor 模型给出的 token-level logprob
    # 只对本 director 训练的座位（Qwen seat）填；其他 API 座位 = None
    prompt: Optional[str] = None
    logprobs: Optional[List[float]] = None  # len == len(tokens)
    tokens: Optional[List[str]] = None       # token 字符串

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrajectoryRecorder:
    """聚合一局所有 Agent 的 trajectory。线程不安全（同进程单局架构下不需要）。"""

    steps: List[TrajectoryStep] = field(default_factory=list)
    _next_id: int = 0

    def record(
        self,
        agent: str,
        phase: str,
        day: int,
        decision_type: str,
        obs: Dict[str, Any],
        action: Any,
        candidates: Optional[List[str]] = None,
    ) -> TrajectoryStep:
        step = TrajectoryStep(
            step_id=self._next_id,
            agent=agent,
            phase=phase,
            day=day,
            decision_type=decision_type,
            obs=copy.deepcopy(obs),
            candidates=list(candidates) if candidates else None,
            action=action,
        )
        self._next_id += 1
        self.steps.append(step)
        return step

    def steps_in_phase(self, phase: str, agent: Optional[str] = None) -> List[TrajectoryStep]:
        return [
            s for s in self.steps
            if s.phase == phase and (agent is None or s.agent == agent)
        ]

    def all_for(self, agent: str) -> List[TrajectoryStep]:
        return [s for s in self.steps if s.agent == agent]

    def fill_episode_reward(self, episode_reward_by_agent: Dict[str, float]) -> None:
        """局末把每条记录的 reward_episode 填上。"""
        for step in self.steps:
            step.reward_episode = float(episode_reward_by_agent.get(step.agent, 0.0))

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "count": len(self.steps),
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


def snapshot_belief(belief: Optional[BeliefState]) -> Optional[dict]:
    """把 BeliefState 序列化进 obs。已 deepcopy 安全。"""
    if belief is None:
        return None
    return {
        "holder": belief.holder,
        "beliefs": copy.deepcopy(belief.beliefs),
        "locked": copy.deepcopy(belief.locked),
    }
