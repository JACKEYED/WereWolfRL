# 文件作用：所有 LLM 调用与 prompt 构造。函数以 director 为首参数。
# 这里集中处理：response 模型、上下文格式化、ask_text / ask_choice、失败兜底。

from typing import Optional, Sequence

from pydantic import BaseModel, Field

from modules.werewolf.rules import ROLE_GOALS
from modules.werewolf.text_utils import clean_text, join_names, match_choice


class TextResponse(BaseModel):
    res: str = Field(description="角色要说的话或内部判断，使用中文，简洁自然。")


class ChoiceResponse(BaseModel):
    res: str = Field(description="从候选项中选择一个，必须原样返回候选项文本。")


def public_context(director, limit: int = 36) -> str:
    return "\n".join(f"- {item}" for item in director.public_log[-limit:])


def private_context(director, name: str, limit: int = 24) -> str:
    return "\n".join(f"- {item}" for item in director.private_log.get(name, [])[-limit:])


def agent_profile(director, name: str) -> str:
    agent = director.game.get_agent(name)
    scratch = agent.scratch.config
    return (
        f"{name}，{scratch.get('age', '未知')}岁。"
        f"天性：{scratch.get('innate', '')}。"
        f"经历：{scratch.get('learned', '')}。"
        f"当前状态：{agent.scratch.currently}"
    )


def build_agent_prompt(director, name: str, phase: str, task: str, *, response_kind: str) -> str:
    """构造给 Agent 的完整 prompt：身份 + 公开/私密上下文 + 任务 + 输出格式约束。"""
    player = director.players[name]
    known = private_context(director, name)
    public = public_context(director)

    peers = ""
    if player.role == "werewolf":
        wolves = [n for n in director.players_order if n != name and director.players[n].role == "werewolf"]
        peers = f"\n你的狼队友：{join_names(wolves)}。"

    checked = ""
    if player.role == "seer":
        checks = director.seer_checks.get(name, {})
        checked = "\n你的查验记录：" + ("；".join(f"{k}={v}" for k, v in checks.items()) or "暂无")

    output_spec = (
        '只输出 JSON：{"res": "..."}。'
        if response_kind == "text"
        else '只输出 JSON：{"res": "候选项原文"}，不要输出候选项之外的内容。'
    )
    return f"""你正在民国年间的江南古镇里参与一场十二人狼人杀。你必须像角色本人一样思考、措辞。

角色档案：
{agent_profile(director, name)}

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
4. {output_spec}
"""


def ask_text(director, name: str, phase: str, task: str, *, fallback: str, max_chars: int = 160) -> str:
    """让某 Agent 输出自由文本；失败回到 fallback。"""
    if not director.use_llm:
        return clean_text(fallback, max_chars)

    agent = director.game.get_agent(name)
    prompt = build_agent_prompt(director, name, phase, task, response_kind="text")
    try:
        return agent._llm.completion(
            prompt=prompt,
            return_type=TextResponse,
            callback=lambda res: clean_text(res, max_chars),
            failsafe=clean_text(fallback, max_chars),
            caller="werewolf_text",
            temperature=0.75,
        )
    except Exception as exc:
        director.add_record("system", phase, f"{name} 文本决策失败，使用兜底：{exc}")
        return clean_text(fallback, max_chars)


def ask_choice(
    director,
    name: str,
    phase: str,
    task: str,
    choices: Sequence[str],
    *,
    fallback: Optional[str] = None,
) -> str:
    """让某 Agent 从候选项里选一个；失败回到 fallback。"""
    choices = list(dict.fromkeys(choices))
    if not choices:
        return ""
    fallback = fallback if fallback in choices else choices[0]
    if not director.use_llm:
        return fallback

    agent = director.game.get_agent(name)
    prompt = build_agent_prompt(
        director,
        name,
        phase,
        task + "\n候选项：\n" + "\n".join(f"- {choice}" for choice in choices),
        response_kind="choice",
    )
    try:
        return agent._llm.completion(
            prompt=prompt,
            return_type=ChoiceResponse,
            callback=lambda res: match_choice(res, choices, fallback),
            failsafe=fallback,
            caller="werewolf_choice",
            temperature=0.35,
        )
    except Exception as exc:
        director.add_record("system", phase, f"{name} 选择决策失败，使用兜底：{exc}")
        return fallback
