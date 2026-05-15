# 文件作用：所有 LLM 调用。prompt 构造已迁移至 modules.prompt。
# 这里集中处理：response 模型、ask_text / ask_choice、失败兜底。

from typing import Optional, Sequence

from pydantic import BaseModel, Field

from modules.prompt import build_agent_prompt
from modules.werewolf.text_utils import clean_text, match_choice


class TextResponse(BaseModel):
    res: str = Field(description="角色要说的话或内部判断，使用中文，简洁自然。")


class ChoiceResponse(BaseModel):
    res: str = Field(description="从候选项中选择一个，必须原样返回候选项文本。")


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
