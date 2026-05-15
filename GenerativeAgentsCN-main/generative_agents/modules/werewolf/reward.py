# 文件作用：为 RL 训练计算 step-level 和 episode-level 奖励。
# 核心思想：用 belief_state 的位移作为 dense reward；用最终胜负作为 sparse reward。

from typing import Dict, List, Optional, Sequence

from modules.werewolf.beliefs import BeliefState


# 阵营 → 该阵营关心的"目标身份"
GOOD_TEAM_ROLES = {"seer", "witch", "hunter", "guard", "villager"}


def step_reward_for_speech(
    actor: str,
    actor_role: str,
    prior_beliefs: Dict[str, BeliefState],
    posterior_beliefs: Dict[str, BeliefState],
    real_roles: Dict[str, str],
    alive: Sequence[str],
) -> float:
    """actor 在某阶段做的所有发言，整体让其他存活玩家对自己/狼队的判断移动了多少。

    - 狼人：希望别人对自己 P(werewolf) 下降
      reward = - Σ_listener Δ P_listener(actor = werewolf)   (越负越好，反符号变正)
    - 好人阵营：希望其他人对真狼的 P(werewolf) 上升
      reward = Σ_listener Σ_wolf Δ P_listener(wolf = werewolf)
    """
    listeners = [n for n in alive if n != actor]
    if not listeners:
        return 0.0

    if actor_role == "werewolf":
        deltas = []
        for listener in listeners:
            prior = prior_beliefs.get(listener)
            post = posterior_beliefs.get(listener)
            if not prior or not post:
                continue
            p_prior = prior.p_role(actor, "werewolf")
            p_post = post.p_role(actor, "werewolf")
            deltas.append(p_prior - p_post)  # 让别人怀疑我下降 → 正 reward
        return sum(deltas) / max(1, len(deltas))

    # 好人阵营：希望听众对所有真狼的怀疑度上升
    wolves = [n for n in alive if real_roles.get(n) == "werewolf"]
    if not wolves:
        return 0.0
    deltas = []
    for listener in listeners:
        prior = prior_beliefs.get(listener)
        post = posterior_beliefs.get(listener)
        if not prior or not post:
            continue
        for w in wolves:
            if w == listener:
                continue
            p_prior = prior.p_role(w, "werewolf")
            p_post = post.p_role(w, "werewolf")
            deltas.append(p_post - p_prior)  # 别人对狼怀疑度上升 → 正 reward
    return sum(deltas) / max(1, len(deltas)) if deltas else 0.0


def step_reward_for_vote(
    voter: str,
    voter_role: str,
    target: str,
    real_roles: Dict[str, str],
) -> float:
    """投票即时奖励：投对一只狼 +1，投空 / 投错 -0.3。
    放逐生效或带飞效果由 episode 奖励兜底。
    """
    target_real = real_roles.get(target)
    voter_is_wolf = voter_role == "werewolf"
    target_is_wolf = target_real == "werewolf"

    if voter_is_wolf:
        # 狼投票：投同伴 -1，投好人 +0.5
        return -1.0 if target_is_wolf else 0.5
    # 好人投票：投狼 +1，投同阵营 -0.3
    return 1.0 if target_is_wolf else -0.3


def step_reward_for_skill(
    actor_role: str,
    skill: str,
    target: Optional[str],
    real_roles: Dict[str, str],
) -> float:
    """夜间技能即时奖励。

    - 预言家查狼 +1，查好人 -0.1（信息少但不亏）
    - 女巫救对（被刀者是好人）+1，救自己仅首夜 +0.3，毒中狼 +1，毒中好人 -1.5
    - 守卫守自己 +0.2，守对（次日被刀者）+1，守错 0
    - 狼刀好人 +0.7，刀同伴 -2（不应发生）
    - 猎人临死带走狼 +1，带走好人 -1
    """
    if not target:
        return 0.0
    target_real = real_roles.get(target)
    target_is_wolf = target_real == "werewolf"

    if actor_role == "seer":
        return 1.0 if target_is_wolf else -0.1
    if actor_role == "guard":
        return 0.2 if target == "self" else (1.0 if not target_is_wolf else 0.0)
    if actor_role == "witch":
        if skill == "save":
            return 1.0 if not target_is_wolf else -0.5
        if skill == "poison":
            return 1.0 if target_is_wolf else -1.5
    if actor_role == "werewolf" and skill == "kill":
        return 0.7 if not target_is_wolf else -2.0
    if actor_role == "hunter" and skill == "shoot":
        return 1.0 if target_is_wolf else -1.0
    return 0.0


def episode_reward(winner: Optional[str], actor_role: str) -> float:
    """局末终奖：阵营赢 +1，输 -1，未决 0。"""
    if not winner:
        return 0.0
    actor_camp = "狼人阵营" if actor_role == "werewolf" else "好人阵营"
    return 1.0 if winner == actor_camp else -1.0
