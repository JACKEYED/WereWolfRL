# 文件作用：prompt 包入口。路径：dispatcher 派发 + social/game 两套独立文案。
#   - 新代码请使用：get_task(scene_mode, key, **kwargs) / build_agent_prompt(director, ...)
#   - 旧代码导入的常量（DAY_SPEECH_TASK 等）作为 social 模式的兼容垫片保留。

from .scratch import Scratch
from .dispatcher import (
    # 新统一入口
    build_agent_prompt,
    get_task,
    phase_label,
    public_context,
    private_context,
    # 兼容垫片（== social 版本）
    agent_profile,
    DAY_SPEECH_TASK,
    DEBATE_TARGET_TASK,
    debate_question_task,
    debate_answer_task,
    TIE_DEFENSE_TASK,
    vote_task,
    WEREWOLF_TARGET_TASK,
    werewolf_speech_task,
    GUARD_TASK,
    SEER_TASK,
    witch_antidote_task,
    WITCH_POISON_TASK,
    social_chat_task,
    HUNTER_SHOT_TASK,
)

__all__ = [
    "Scratch",
    # 新统一入口
    "build_agent_prompt", "get_task", "phase_label",
    "public_context", "private_context", "agent_profile",
    # 兼容（social 默认）
    "DAY_SPEECH_TASK", "DEBATE_TARGET_TASK", "debate_question_task", "debate_answer_task",
    "TIE_DEFENSE_TASK", "vote_task",
    "WEREWOLF_TARGET_TASK", "werewolf_speech_task",
    "GUARD_TASK", "SEER_TASK", "witch_antidote_task", "WITCH_POISON_TASK",
    "social_chat_task", "HUNTER_SHOT_TASK",
]
