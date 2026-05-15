# 文件作用：狼人杀标准 12 人板的常量和纯规则函数。
# 设计原则：本模块零运行时副作用，可独立 import 做单元测试。

import random as _random_module
from typing import Dict, List, Optional, Sequence, Tuple


ROLE_DECK: List[str] = [
    "werewolf", "werewolf", "werewolf", "werewolf",
    "seer", "witch", "hunter", "guard",
    "villager", "villager", "villager", "villager",
]

ROLE_NAMES: Dict[str, str] = {
    "werewolf": "狼人",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
    "guard": "守卫",
    "villager": "村民",
}

ROLE_GOALS: Dict[str, str] = {
    "werewolf": "隐藏狼队身份，误导白天讨论，并在夜晚与狼队配合击杀好人。",
    "seer": "每晚查验一名玩家阵营，白天用可信但不轻易暴露的方式引导好人。",
    "witch": "拥有一瓶解药和一瓶毒药，判断何时救人或毒人，并在白天隐藏神职身份。",
    "hunter": "死亡时可以开枪带走一名玩家，平时需要观察谁最值得被带走。",
    "guard": "每晚守护一名玩家，不能连续两晚守护同一人，尽量保护关键好人。",
    "villager": "没有夜间技能，只能依靠发言、投票、观察和记忆找出狼人。",
}

# 安全上限，避免极端情况下永远跑不完。
SAFETY_DAY_LIMIT: int = 12


def resolve_night_deaths(
    wolf_target: Optional[str],
    guard_target: Optional[str],
    saved_by_witch: Optional[str],
    poison_target: Optional[str],
) -> Tuple[Dict[str, List[str]], List[str]]:
    """根据夜间四路输入计算实际死亡名单。

    标准规则要点：
      - 同守同救（守卫和女巫救药都指向被刀者）→ 仍死，互冲抵消。
      - 仅被守护 → 不死（平安夜元素）。
      - 仅被女巫救 → 不死。
      - 都没碰 → 死于狼刀。
      - 被女巫毒杀的，无论是否被守护/救药，都死。

    返回 (deaths, narration)：
      deaths: {target_name: [reason, ...]}
      narration: 给 secret 日志写的几条文本（描述抵消/救援）
    """
    deaths: Dict[str, List[str]] = {}
    narration: List[str] = []

    if wolf_target:
        guarded = wolf_target == guard_target
        saved = wolf_target == saved_by_witch
        if guarded and saved:
            deaths.setdefault(wolf_target, []).append("同守同救")
            narration.append(f"{wolf_target} 同时被守卫守护与女巫救起，互冲抵消，仍然死亡。")
        elif guarded:
            narration.append(f"守卫保护了 {wolf_target}，狼刀没有造成死亡。")
        elif saved:
            narration.append(f"女巫使用解药救下了 {wolf_target}。")
        else:
            deaths.setdefault(wolf_target, []).append("狼人夜袭")

    if poison_target:
        deaths.setdefault(poison_target, []).append("女巫毒药")

    return deaths, narration


def check_winner(alive_wolves: Sequence[str], alive_good: Sequence[str]) -> Optional[str]:
    """胜负判定（屠边/灭杀）：
      - 狼人全死 → 好人阵营赢
      - 狼人数 >= 好人数 → 狼人阵营赢
      - 否则 None
    """
    if not alive_wolves:
        return "好人阵营"
    if len(alive_wolves) >= len(alive_good):
        return "狼人阵营"
    return None


def tally(values: Sequence[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return counts


def resolve_vote(votes: Dict[str, str]) -> Optional[str]:
    """唯一最高票胜出；平票返回 None。"""
    if not votes:
        return None
    counts = tally(list(votes.values()))
    high = max(counts.values())
    tied = [target for target, count in counts.items() if count == high]
    return tied[0] if len(tied) == 1 else None


def tied_candidates(votes: Dict[str, str]) -> List[str]:
    if not votes:
        return []
    counts = tally(list(votes.values()))
    high = max(counts.values())
    return [target for target, count in counts.items() if count == high]


def majority_choice(values: Sequence[str], rng: _random_module.Random) -> str:
    """从多数项中挑一个；平票用 rng 决断。values 不可为空。"""
    counts = tally(list(values))
    high = max(counts.values())
    tied = [v for v, c in counts.items() if c == high]
    return rng.choice(tied)
