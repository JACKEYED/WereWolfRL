# 文件作用：导出 Scratch 人设状态类和所有 Prompt 定义。

from .scratch import Scratch
from .prompt import (
    build_agent_prompt,
    public_context,
    private_context,
    agent_profile,
    # 白天阶段
    DAY_SPEECH_TASK,
    DEBATE_TARGET_TASK,
    debate_question_task,
    debate_answer_task,
    TIE_DEFENSE_TASK,
    vote_task,
    # 夜晚阶段
    WEREWOLF_TARGET_TASK,
    werewolf_speech_task,
    GUARD_TASK,
    SEER_TASK,
    witch_antidote_task,
    WITCH_POISON_TASK,
    # 社交阶段
    social_chat_task,
    # 猎人
    HUNTER_SHOT_TASK,
)
