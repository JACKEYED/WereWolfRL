# 文件作用：用 LLM 评判某玩家在一段事件后对其他玩家的身份概率更新。
# 颗粒度：每阶段末（不是每条发言），每位存活听众调用一次。

import json
import re
from typing import Dict, List, Sequence

from pydantic import BaseModel, Field

from modules.werewolf.beliefs import (
    BeliefState,
    ROLE_KEYS,
    merge_with_locks,
    normalize_distribution,
)


class JudgeResponse(BaseModel):
    """LLM 输出格式约束。"""
    beliefs: Dict[str, Dict[str, float]] = Field(
        description="对每个未锁定玩家的身份概率分布；每个目标的 6 个 role 概率加起来应≈1。"
    )


def update_belief_via_llm(
    director,
    witness_name: str,
    prior: BeliefState,
    phase_label: str,
    new_events: Sequence[str],
) -> BeliefState:
    """让 witness 在看完 new_events 后重估对每个非锁定玩家的身份分布。

    fallback：LLM 不可用 / 返回错误时返回原 prior 不变。
    """
    if not director.use_llm or not new_events:
        return prior  # 无 LLM 模式不更新

    player = director.players.get(witness_name)
    if not player or not player.alive:
        return prior

    targets = [t for t in prior.beliefs.keys() if t not in prior.locked]
    if not targets:
        return prior  # 全部锁定，无需更新

    prompt = _build_judge_prompt(director, witness_name, prior, phase_label, list(new_events), targets)

    try:
        agent = director.game.get_agent(witness_name)
        raw = agent._llm.completion(
            prompt=prompt,
            return_type=JudgeResponse,
            callback=lambda res: _parse_response(res, targets),
            failsafe=None,
            caller="werewolf_judge",
            temperature=0.3,
        )
    except Exception as exc:
        director.add_record("system", phase_label, f"{witness_name} belief 更新失败：{exc}")
        return prior

    if not raw:
        return prior

    # 归一化 + 合并锁定项
    cleaned: Dict[str, Dict[str, float]] = {}
    for target in targets:
        cleaned[target] = normalize_distribution(raw.get(target, {}))
    merged = merge_with_locks(cleaned, prior.locked)

    return BeliefState(holder=witness_name, beliefs=merged, locked=dict(prior.locked))


def _build_judge_prompt(
    director,
    witness_name: str,
    prior: BeliefState,
    phase_label: str,
    new_events: List[str],
    targets: List[str],
) -> str:
    player = director.players[witness_name]
    alive = director.alive_names()
    alive_text = "、".join(alive)
    targets_text = "、".join(targets)

    own_block = f"你自己：{player.role_name}（{player.camp}）。"
    locked_block = ""
    if prior.locked:
        items = []
        for t, r in prior.locked.items():
            items.append(f"{t}=100% {_role_zh(r)}")
        locked_block = "你已经 100% 确认的玩家身份：" + "；".join(items) + "。\n"

    # 把当前 belief 渲染成可读文本
    prior_text = prior.render_text(top_k=6)

    events_block = "\n".join(f"- {e}" for e in new_events) if new_events else "（无新事件）"

    return f"""你是 {witness_name}，正在民国江南古镇玩 12 人狼人杀。
身份分布固定：4 狼人、1 预言家、1 女巫、1 猎人、1 守卫、4 村民，全镇 12 人。
{own_block}
{locked_block}存活玩家：{alive_text}

【你当前的心理判断】（每条是你对一个人的身份概率分布）：
{prior_text}

【刚刚发生的事件】（{phase_label} 阶段，按时间顺序）：
{events_block}

任务：基于以上事件，**重新估计**你对以下玩家身份的概率分布：
{targets_text}

判断要点：
1. 跳神 / 发对刀 / 站边 / 投票 是强信号
2. 言行矛盾、回避问题、抢话头是弱嫌疑信号
3. 不要完全无视先验，但允许较大幅度调整
4. 概率分布要反映"几个候选都有可能"的不确定性，不要轻易给 0% 或 100%
5. 必须只考虑你听到/亲历的事件，不能编造未发生的事

只输出 JSON：
{{
  "beliefs": {{
    "{targets[0]}": {{"werewolf": 0.x, "seer": 0.x, "witch": 0.x, "hunter": 0.x, "guard": 0.x, "villager": 0.x}}
    {('...' if len(targets) > 1 else '')}
  }}
}}
每个目标的 6 个概率必须加起来约等于 1（系统会再做归一）。
"""


def _parse_response(raw, targets: List[str]) -> Dict[str, Dict[str, float]]:
    """从 LLM 输出（可能是 JudgeResponse 或原始字符串）抽出 beliefs 字典。"""
    if isinstance(raw, JudgeResponse):
        return raw.beliefs
    if isinstance(raw, dict):
        return raw.get("beliefs", raw)
    text = str(raw).strip()
    # 兜底：直接找 {...}
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group())
    except Exception:
        return {}
    if "beliefs" in parsed:
        return parsed["beliefs"]
    return parsed if all(t in parsed for t in targets[:1]) else {}


_ROLE_ZH_LOCAL = {
    "werewolf": "狼人", "seer": "预言家", "witch": "女巫",
    "hunter": "猎人", "guard": "守卫", "villager": "村民",
}

def _role_zh(role: str) -> str:
    return _ROLE_ZH_LOCAL.get(role, role)
