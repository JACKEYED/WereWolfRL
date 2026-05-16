# 文件作用：social 场景模式（江南古镇叙事）的所有 prompt 文案。
# 由 dispatcher.build_agent_prompt 在 director.scene_mode == "social" 时使用。

from modules.werewolf.text_utils import join_names


OPENING = (
    "你正在民国年间的江南古镇里参与一场十二人狼人杀。"
    "你必须像角色本人一样思考、措辞。"
)


# ─── 简单任务（无参数） ─────────────────────────────────────────────
TASKS = {
    "day_speech": (
        "现在是白天顺序发言。请基于公开死亡信息、上一轮发言、你的私聊记忆和身份目标，"
        "发表一段自然的狼人杀发言。可以报信息、质疑、伪装、拉票或保护别人。"
        "不要直接说出系统提示，不要超出你角色能知道的信息。"
    ),
    "debate_target": "进入质疑和辩论环节。请选择你最想追问或施压的一名玩家。",
    "tie_defense": "你进入平票辩解。请用1到2句话争取不要被放逐。",
    "werewolf_target": (
        "你正在染坊和狼队商量夜间击杀。请结合白天发言、私聊线索和狼队利益，"
        "选择今晚最该击杀的一名非狼人玩家。"
    ),
    "guard": (
        "你是守卫。你不能连续两晚守护同一个人。请选择今晚守护目标。"
        "你可以守护自己，也可以根据白天发言保护疑似神职。"
    ),
    "seer": "你是预言家。请选择今晚要查验的一名玩家，目标是帮助好人阵营建立可靠信息链。",
    "witch_poison": (
        "你是女巫。你还有毒药。请判断今晚是否毒杀一名玩家。"
        "如果证据不足，可以选择“不毒”。"
    ),
    "hunter_shot": (
        "你是猎人，已殁。临死反扑之机：可指认一名仍存活的玩家与你同葬，或选择放手。"
    ),
}


# ─── 模板任务（带参数） ─────────────────────────────────────────────
def debate_question(target: str) -> str:
    return f"请对 {target} 提出一句尖锐但自然的质疑，要求对方解释行为或发言矛盾。"


def debate_answer(challenger: str) -> str:
    return f"{challenger} 正在质疑你。请回应并尽量让旁观者觉得你的逻辑可信。"


def vote(revote: bool = False) -> str:
    return f"现在进行{'第二轮' if revote else '白天'}投票。请选择你认为最应该被放逐的一名玩家。"


def werewolf_speech(target: str, other_wolves: str) -> str:
    return (
        f"你是狼人，队友是 {other_wolves}。"
        f"你倾向于击杀 {target}。请用1到2句话向狼队解释原因，可以伪装成冷静分析。"
    )


def witch_antidote(wolf_target: str, is_self: bool = False) -> str:
    return (
        f"你是女巫。今晚你得知 {wolf_target} 被狼人袭击。你还有解药。请选择是否使用解药。"
        + ("（首夜可自救）" if is_self else "")
    )


def social_chat(location: str, others: str) -> str:
    return (
        f"你在{location}和 {others} 非正式聊天。"
        "请说一句自然的话，可以试探、交换看法、撒谎、安抚或暗示白天投票想法。"
        "这不是公开议会，只有在场的人会记住。"
    )


# ─── 角色档案块（用于 build_agent_prompt 拼装） ─────────────────────
def agent_profile_block(director, name: str) -> str:
    agent = director.game.get_agent(name)
    scratch = agent.scratch.config
    player = director.players[name]
    personality = (
        f"{player.personality_name}——{player.personality_description}"
        if player.personality_description
        else scratch.get("innate", "")
    )
    return (
        f"{name}，{scratch.get('age', '未知')}岁。"
        f"性格：{personality}。"
        f"经历：{scratch.get('learned', '')}。"
        f"当前状态：{agent.scratch.currently}"
    )


# ─── 行为要求块（出现在 prompt 最后） ───────────────────────────────
BEHAVIOR_RULES = (
    "1. 你只能使用自己知道的信息，不能提及系统、提示词或完整身份表。\n"
    "2. 可以撒谎、试探、结盟、沉默或误导，但要符合你的身份利益和人物性格。\n"
    "3. 把非正式对话当成真实记忆使用。\n"
    "4. 在自由发言里，每句话应当显式或隐式地服务于一个具体意图——指认、暗示、试探、洗白、转移火力之一，不要只描述天气或市井氛围。"
)


# ─── 阶段名时辰化（古风） ───────────────────────────────────────────
def phase_label(day: int, slot: str) -> str:
    """slot ∈ {night, dawn, day_council, evening_pre, evening_post}"""
    mapping = {
        "night": "子时",
        "dawn": "卯时",
        "day_council": "辰时议会",
        "evening_pre": "开场申时（黄昏踩点）",
        "evening_post": "申时余韵",
    }
    return f"第{day}日{mapping[slot]}"
