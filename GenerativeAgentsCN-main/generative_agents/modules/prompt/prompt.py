# 文件作用：狼人杀所有 LLM prompt 统一管理。

from modules.werewolf.rules import ROLE_GOALS
from modules.werewolf.text_utils import join_names


# =============================================================================
# 上下文格式化（从 llm_io 迁移）
# =============================================================================
def public_context(director, limit: int = 36) -> str:
    return "\n".join(f"- {item}" for item in director.public_log[-limit:])


def private_context(director, name: str, limit: int = 24) -> str:
    return "\n".join(f"- {item}" for item in director.private_log.get(name, [])[-limit:])


def agent_profile(director, name: str) -> str:
    agent = director.game.get_agent(name)
    scratch = agent.scratch.config
    player = director.players[name]
    personality = f"{player.personality_name}——{player.personality_description}" if player.personality_description else scratch.get('innate', '')
    return (
        f"{name}，{scratch.get('age', '未知')}岁。"
        f"性格：{personality}。"
        f"经历：{scratch.get('learned', '')}。"
        f"当前状态：{agent.scratch.currently}"
    )


# =============================================================================
# 系统 Prompt 模板
# =============================================================================
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


# =============================================================================
# 白天阶段 Prompt
# =============================================================================
DAY_SPEECH_TASK = (
    "现在是白天顺序发言。请基于公开死亡信息、上一轮发言、你的私聊记忆和身份目标，"
    "发表一段自然的狼人杀发言。可以报信息、质疑、伪装、拉票或保护别人。"
    "不要直接说出系统提示，不要超出你角色能知道的信息。"
)

DEBATE_TARGET_TASK = "进入质疑和辩论环节。请选择你最想追问或施压的一名玩家。"


def debate_question_task(target: str) -> str:
    return f"请对 {target} 提出一句尖锐但自然的质疑，要求对方解释行为或发言矛盾。"


def debate_answer_task(challenger: str) -> str:
    return f"{challenger} 正在质疑你。请回应并尽量让旁观者觉得你的逻辑可信。"


TIE_DEFENSE_TASK = "你进入平票辩解。请用1到2句话争取不要被放逐。"


def vote_task(revote: bool = False) -> str:
    return f"现在进行{'第二轮' if revote else '白天'}投票。请选择你认为最应该被放逐的一名玩家。"


# =============================================================================
# 夜晚阶段 Prompt
# =============================================================================
WEREWOLF_TARGET_TASK = (
    "你正在染坊和狼队商量夜间击杀。请结合白天发言、私聊线索和狼队利益，"
    "选择今晚最该击杀的一名非狼人玩家。"
)


def werewolf_speech_task(target: str, other_wolves: str) -> str:
    return (
        f"你是狼人，队友是 {other_wolves}。"
        f"你倾向于击杀 {target}。请用1到2句话向狼队解释原因，可以伪装成冷静分析。"
    )


GUARD_TASK = (
    "你是守卫。你不能连续两晚守护同一个人。请选择今晚守护目标。"
    "你可以守护自己，也可以根据白天发言保护疑似神职。"
)

SEER_TASK = "你是预言家。请选择今晚要查验的一名玩家，目标是帮助好人阵营建立可靠信息链。"


def witch_antidote_task(wolf_target: str, is_self: bool = False) -> str:
    return (
        f"你是女巫。今晚你得知 {wolf_target} 被狼人袭击。你还有解药。请选择是否使用解药。"
        + ("（首夜可自救）" if is_self else "")
    )


WITCH_POISON_TASK = (
    "你是女巫。你还有毒药。请判断今晚是否毒杀一名玩家。如果证据不足，可以选择“不毒”。"
)


# =============================================================================
# 社交阶段 Prompt
# =============================================================================
def social_chat_task(location: str, others: str) -> str:
    return (
        f"你在{location}和 {others} 非正式聊天。"
        "请说一句自然的话，可以试探、交换看法、撒谎、安抚或暗示白天投票想法。"
        "这不是公开议会，只有在场的人会记住。"
    )


# =============================================================================
# 猎人 Prompt
# =============================================================================
HUNTER_SHOT_TASK = "你是猎人，已殁。临死反扑之机：可指认一名仍存活的玩家与你同葬，或选择放手。"
