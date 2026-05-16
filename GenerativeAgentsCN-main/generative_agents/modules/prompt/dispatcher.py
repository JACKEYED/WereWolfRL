# 文件作用：scene_mode 派发器。根据 director.scene_mode 在 social.py 和 game.py 之间选取 prompt 文案。
# 对外暴露：
#   - get_task(scene_mode, key, **kwargs)：取任意阶段任务文案
#   - build_agent_prompt(director, name, phase, task, response_kind)：拼装完整 prompt
#   - phase_label(scene_mode, day, slot)：取当前阶段在该模式下的展示名

from modules.prompt import social as _social
from modules.prompt import game as _game
from modules.werewolf.rules import ROLE_GOALS
from modules.werewolf.text_utils import join_names


# 上下文格式化（mode 无关，直接共用）
def public_context(director, limit: int = 36) -> str:
    return "\n".join(f"- {item}" for item in director.public_log[-limit:])


def private_context(director, name: str, limit: int = 24) -> str:
    return "\n".join(f"- {item}" for item in director.private_log.get(name, [])[-limit:])


def _mode(scene_mode: str):
    return _game if scene_mode == "game" else _social


# ─── 公共入口：任务文案 ─────────────────────────────────────────────
def get_task(scene_mode: str, key: str, **kwargs) -> str:
    """统一从 social.py / game.py 取任务文案。

    支持的 key（含参数）：
      - day_speech / debate_target / tie_defense
      - werewolf_target / guard / seer / witch_poison / hunter_shot
      - debate_question(target=)
      - debate_answer(challenger=)
      - vote(revote=)
      - werewolf_speech(target=, other_wolves=)
      - witch_antidote(wolf_target=, is_self=)
      - social_chat(location=, others=)
    """
    mod = _mode(scene_mode)
    # 模板任务（带参数）
    if key == "debate_question":
        return mod.debate_question(**kwargs)
    if key == "debate_answer":
        return mod.debate_answer(**kwargs)
    if key == "vote":
        return mod.vote(**kwargs)
    if key == "werewolf_speech":
        return mod.werewolf_speech(**kwargs)
    if key == "witch_antidote":
        return mod.witch_antidote(**kwargs)
    if key == "social_chat":
        return mod.social_chat(**kwargs)
    # 简单任务
    return mod.TASKS.get(key, _social.TASKS.get(key, ""))


def phase_label(scene_mode: str, day: int, slot: str) -> str:
    return _mode(scene_mode).phase_label(day, slot)


# ─── 公共入口：完整 prompt ──────────────────────────────────────────
def build_agent_prompt(
    director, name: str, phase: str, task: str, *, response_kind: str
) -> str:
    """拼装给 Agent 的完整 prompt：opening + 档案 + 身份 + belief + 公私上下文 + 任务 + 行为规则 + 输出格式。"""
    mode = director.scene_mode if hasattr(director, "scene_mode") else "social"
    mod = _mode(mode)
    player = director.players[name]
    known = private_context(director, name)
    public = public_context(director)

    peers = ""
    if player.role == "werewolf":
        wolves = [
            n for n in director.players_order
            if n != name and director.players[n].role == "werewolf"
        ]
        peers = f"\n你的狼队友：{join_names(wolves)}。"

    checked = ""
    if player.role == "seer":
        checks = director.seer_checks.get(name, {})
        checked = "\n你的查验记录：" + (
            "；".join(f"{k}={v}" for k, v in checks.items()) or "暂无"
        )

    # 心里对其他玩家的当前判断（belief）
    belief_block = ""
    bs = director.belief_of(name) if hasattr(director, "belief_of") else None
    if bs and bs.beliefs:
        belief_block = (
            "\n你心里对其他玩家的当前判断（每行只列前 3 个最可能身份）：\n"
            + bs.render_text(top_k=3)
            + "\n请基于这个判断采取行动；如果新事件让你想改变判断，体现在你的发言里。"
        )

    pressure_block = (
        f"\n场上：第 {director.day} 日，存活 {len(director.alive_names())} 人。"
    )

    output_spec = (
        '只输出 JSON：{"res": "..."}。'
        if response_kind == "text"
        else '只输出 JSON：{"res": "候选项原文"}，不要输出候选项之外的内容。'
    )

    return f"""{mod.OPENING}

角色档案：
{mod.agent_profile_block(director, name)}

秘密身份：{player.role_name}（{player.camp}）。
身份目标：{ROLE_GOALS[player.role]}{peers}{checked}{belief_block}
{pressure_block}

当前阶段：{phase}

公开时间线：
{public or "暂无公开信息。"}

你的私密记忆和局部观察：
{known or "暂无私密线索。"}

当前任务：
{task}

行为要求：
{mod.BEHAVIOR_RULES}
5. {output_spec}
"""


# ─── 兼容层：legacy 常量入口 ────────────────────────────────────────
# 已有 phases/*.py 仍 import 下面这些；保留为 social 版本以保持向后兼容。
# 新代码应改用 get_task(scene_mode, ...) 形式。
DAY_SPEECH_TASK = _social.TASKS["day_speech"]
DEBATE_TARGET_TASK = _social.TASKS["debate_target"]
TIE_DEFENSE_TASK = _social.TASKS["tie_defense"]
WEREWOLF_TARGET_TASK = _social.TASKS["werewolf_target"]
GUARD_TASK = _social.TASKS["guard"]
SEER_TASK = _social.TASKS["seer"]
WITCH_POISON_TASK = _social.TASKS["witch_poison"]
HUNTER_SHOT_TASK = _social.TASKS["hunter_shot"]


def debate_question_task(target: str) -> str:
    return _social.debate_question(target)


def debate_answer_task(challenger: str) -> str:
    return _social.debate_answer(challenger)


def vote_task(revote: bool = False) -> str:
    return _social.vote(revote=revote)


def werewolf_speech_task(target: str, other_wolves: str) -> str:
    return _social.werewolf_speech(target, other_wolves)


def witch_antidote_task(wolf_target: str, is_self: bool = False) -> str:
    return _social.witch_antidote(wolf_target, is_self=is_self)


def social_chat_task(location: str, others: str) -> str:
    return _social.social_chat(location, others)


def agent_profile(director, name: str) -> str:
    """保留 legacy 名字，行为 = social.agent_profile_block。"""
    return _social.agent_profile_block(director, name)
