# 文件作用：WerewolfPlayer 玩家状态 + 与玩家身份相关的纯函数（如开局简报、兜底发言）。

from dataclasses import dataclass
from typing import List, Optional, Sequence

from modules.werewolf.rules import ROLE_GOALS, ROLE_NAMES


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


def role_brief(player: WerewolfPlayer, wolf_peers: Sequence[str]) -> str:
    """开局给玩家私下发的身份简报。wolf_peers 只在 player 是狼人时使用。"""
    brief: List[str] = [
        f"你的狼人杀身份是 {player.role_name}，属于{player.camp}。",
        ROLE_GOALS[player.role],
    ]
    if player.role == "werewolf":
        peers = "、".join(wolf_peers) if wolf_peers else "无"
        brief.append(f"你的狼队友是：{peers}。")
    if player.role == "witch":
        brief.append("你有一瓶解药和一瓶毒药，每瓶只能使用一次，且一夜不能同用两药。")
    if player.role == "hunter":
        brief.append("你死亡时可以选择开枪带走一名玩家（被女巫毒药毒杀的情况除外）。")
    if player.role == "guard":
        brief.append("你每晚可以守护一名玩家，但不能连续两晚守护同一人。")
    return " ".join(brief)


def fallback_speech(role: str) -> str:
    """ask_text 失败或 use_llm=False 时的兜底白天发言。"""
    if role == "werewolf":
        return "我先不急着定死谁，但我觉得今天要看谁在带节奏过快，狼很可能藏在主动归票的人里。"
    if role == "seer":
        return "我会更关注发言里的前后矛盾，今天先把信息留清楚，别让票型被情绪带散。"
    if role == "witch":
        return "夜里的结果说明有人在藏视角，我建议大家把昨天私聊和今天投票理由都摊开说。"
    if role == "guard":
        return "我更想听每个人解释自己的怀疑链，单纯跟票的人在我这里会变得很可疑。"
    return "我没有夜间信息，只能从发言和私聊判断。今天我会重点看谁在回避死亡信息。"
