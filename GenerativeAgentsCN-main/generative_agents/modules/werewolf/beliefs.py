# 文件作用：BeliefState 数据结构和初始化辅助。
# 每个存活 Agent 维护一份对其他玩家的身份概率分布，作为 RL 训练的状态空间。

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from modules.werewolf.rules import ROLE_DECK


# 12 人板中每个身份的总数。
ROLE_COUNTS: Dict[str, int] = {role: ROLE_DECK.count(role) for role in set(ROLE_DECK)}

# 6 个身份键，固定顺序便于前端展示。
ROLE_KEYS: List[str] = ["werewolf", "seer", "witch", "hunter", "guard", "villager"]


@dataclass
class BeliefState:
    """holder 这个 Agent 对其他 11 名玩家身份的概率判断。

    - beliefs[target_name][role] = float in [0, 1]，每个 target 的所有 role 概率加起来 = 1
    - locked[target_name] = role  表示 holder 100% 确定这个人的身份（不允许被 LLM 改）
      （own role 不进 beliefs；wolf 已知队友会被 locked 为 werewolf；预言家查验结果也会被锁）
    """

    holder: str
    beliefs: Dict[str, Dict[str, float]] = field(default_factory=dict)
    locked: Dict[str, str] = field(default_factory=dict)

    # ---------- 查询 ----------
    def top_suspect(self, role: str = "werewolf") -> Optional[str]:
        """对 holder 来说，最像 role 的那个人是谁。"""
        if not self.beliefs:
            return None
        return max(self.beliefs.keys(), key=lambda n: self.beliefs[n].get(role, 0.0))

    def p_role(self, target: str, role: str) -> float:
        return self.beliefs.get(target, {}).get(role, 0.0)

    def render_text(self, top_k: int = 3) -> str:
        """把 belief 压成给 LLM 看的中文摘要。每个目标只显示前 top_k 个最可能身份。"""
        if not self.beliefs:
            return "（尚未形成判断）"
        lines: List[str] = []
        for target, dist in self.beliefs.items():
            if target in self.locked:
                lines.append(f"- {target}：[已确认] {_role_zh(self.locked[target])}")
                continue
            ranked = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
            parts = "、".join(f"{_role_zh(r)} {p:.0%}" for r, p in ranked)
            lines.append(f"- {target}：{parts}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"holder": self.holder, "beliefs": self.beliefs, "locked": self.locked}


_ROLE_ZH = {
    "werewolf": "狼人", "seer": "预言家", "witch": "女巫",
    "hunter": "猎人", "guard": "守卫", "villager": "村民",
}


def _role_zh(role: str) -> str:
    return _ROLE_ZH.get(role, role)


# =========================================================================
# 初始化
# =========================================================================
def init_for(
    holder_name: str,
    holder_role: str,
    all_players: Sequence[str],
    wolf_teammates: Sequence[str] = (),
    seer_known_checks: Optional[Dict[str, str]] = None,
) -> BeliefState:
    """根据 holder 的身份和已知信息构造先验 belief。

    - 普通好人 / 神：除去自己身份后，剩余 11 个槽位平均分配
    - 狼人：除去自己 + 已知狼队友后，分配剩余 8 个槽位
    - 预言家：查验过的目标被锁定
    """
    locked: Dict[str, str] = {}
    if wolf_teammates:
        for w in wolf_teammates:
            locked[w] = "werewolf"
    if seer_known_checks:
        for target, claim in seer_known_checks.items():
            # seer_known_checks 给的是 "狼人" 或 "好人"
            # "狼人" → 直接锁 werewolf；"好人" → 仅排除 werewolf 但保留其他可能（不锁定具体身份）
            if claim == "狼人":
                locked[target] = "werewolf"
            # 好人查验不全锁（信息不足以区分神/民），由下面的 prior 处理

    # 计算 holder 视角下"未锁定"那些人的身份池
    remaining_counts = dict(ROLE_COUNTS)
    remaining_counts[holder_role] -= 1  # 自己
    for locked_target, locked_role in locked.items():
        if locked_target in all_players and locked_target != holder_name:
            remaining_counts[locked_role] = max(0, remaining_counts[locked_role] - 1)

    beliefs: Dict[str, Dict[str, float]] = {}
    for player in all_players:
        if player == holder_name:
            continue
        if player in locked:
            # 100% 概率
            beliefs[player] = {r: 0.0 for r in ROLE_KEYS}
            beliefs[player][locked[player]] = 1.0
            continue

        # 未锁定 → 均匀分配剩余池
        # 但要考虑 seer 查到"好人"的情况：那个 target 不应给 werewolf 概率
        zero_roles = set()
        if seer_known_checks and player in seer_known_checks and seer_known_checks[player] == "好人":
            zero_roles.add("werewolf")

        adjusted = {r: (0 if r in zero_roles else remaining_counts[r]) for r in ROLE_KEYS}
        total = sum(adjusted.values())
        if total == 0:
            # 退化：均匀
            beliefs[player] = {r: 1.0 / len(ROLE_KEYS) for r in ROLE_KEYS}
        else:
            beliefs[player] = {r: adjusted[r] / total for r in ROLE_KEYS}

    return BeliefState(holder=holder_name, beliefs=beliefs, locked=dict(locked))


def normalize_distribution(dist: Dict[str, float]) -> Dict[str, float]:
    """把任意 dict[role] 归一化成概率分布；非法/缺失的 key 补 0，再均衡。"""
    cleaned = {r: max(0.0, float(dist.get(r, 0.0))) for r in ROLE_KEYS}
    total = sum(cleaned.values())
    if total <= 0:
        return {r: 1.0 / len(ROLE_KEYS) for r in ROLE_KEYS}
    return {r: v / total for r, v in cleaned.items()}


def merge_with_locks(new_beliefs: Dict[str, Dict[str, float]], locked: Dict[str, str]) -> Dict[str, Dict[str, float]]:
    """LLM 给出新 belief 后，把 locked 那些 target 强制覆盖回 100% 真值。"""
    merged = dict(new_beliefs)
    for target, locked_role in locked.items():
        merged[target] = {r: 0.0 for r in ROLE_KEYS}
        merged[target][locked_role] = 1.0
    return merged
