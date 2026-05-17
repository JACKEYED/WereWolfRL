# 文件作用：game 场景模式（v1 纯狼人杀 RL 训练）的所有 prompt 文案。
# 设计原则：
#   - 直接、操作性强、不带任何古风或地域氛围
#   - 每个任务明确"要求 LLM 输出什么"
#   - 强制 LLM 表态，禁止描述天气/氛围/铺垫
# 由 dispatcher.build_agent_prompt 在 director.scene_mode == "game" 时使用。


OPENING = (
    "你正在参与一场十二人狼人杀。"
    "你的唯一目标是让你的阵营获胜——"
    "狼人阵营需要消灭好人到等于或多于自己的人数，好人阵营需要找出全部 4 名狼人。"
    "你的所有发言、投票、技能选择都应当服务于这个目标。"
    "\n\n语气要求（极其重要）：用现代日常口语，**像在微信狼人杀群里发言**。"
    "**禁止**使用文言风格、四字成语堆砌、人物描写式叙述。"
    "玩家名字虽然有些文气（如陈砚秋、周文卿），但你说话**不能跟着古风走**——把他们当成普通微信好友的名字看待。"
)


# ─── 简单任务（无参数） ─────────────────────────────────────────────
TASKS = {
    "day_speech": (
        "白天发言阶段。基于公开死亡信息和你当前的怀疑判断，发表一段简洁有立场的发言。"
        "你的发言至少要包含以下之一："
        "(a) 指认某位玩家是狼人，并给出依据；"
        "(b) 为某位玩家背书（声称他是好人），并给出依据；"
        "(c) 引用之前的公开事件做推理；"
        "(d) 表明你的投票倾向。"
        "**用现代口语，2-3 句**。禁止文言、禁止小说式描写。"
        "\n示范：'昨晚阿福死了，我觉得是徐慎之的狼刀——他第一发言就在带节奏。我今天投徐慎之。' "
        "或 '我跳预言家，昨晚查的柳青禾是金水。建议优先听她的判断。'"
    ),
    "debate_target": "辩论环节。选择你最想追问或施压的一名玩家。",
    "tie_defense": "你进入平票辩解。用 1-2 句话给出关键自证或反击，避免被放逐。",
    "werewolf_target": (
        "狼队商量今晚刀谁。"
        "结合白天发言、其他狼队友的提议、你对各玩家身份的判断，"
        "选择最该击杀的一名非狼玩家。"
    ),
    "guard": (
        "守卫夜间行动。请选择今晚守护的一名玩家。"
        "规则：不能连续两晚守同一人；可以守自己；优先保护你判断为神职的玩家。"
    ),
    "seer": (
        "预言家夜间行动。请选择今晚查验的一名玩家。"
        "优先查验你怀疑度高的人，以最大化信息收益。"
    ),
    "witch_poison": (
        "女巫毒药决策。是否毒杀一名玩家？"
        "毒药仅一瓶且不可恢复——证据不足请选'不毒'。"
        "若你已锁定某狼人，毒杀是高收益操作。"
    ),
    "hunter_shot": (
        "猎人临死开枪。可以指认并带走一名仍存活的玩家，或选择'不开枪'。"
        "优先带走你判断为狼人的目标。"
    ),
}


# ─── 模板任务（带参数） ─────────────────────────────────────────────
def debate_question(target: str) -> str:
    return (
        f"对 {target} 提出一句具体质疑。"
        f"要求：引用 {target} 之前的具体行为或发言，指出其中的矛盾或可疑点。"
        "不要泛泛而问。"
    )


def debate_answer(challenger: str) -> str:
    return (
        f"{challenger} 在质疑你。请回应他的指控。"
        "要求：要么解释清楚被质疑的行为，要么反向质疑 challenger。"
        "1-2 句话。"
    )


def vote(revote: bool = False) -> str:
    label = "第二轮" if revote else "首轮"
    return f"{label}投票。选择你认为最应被放逐的一名玩家。基于你当前的怀疑判断决定。"


def werewolf_speech(target: str, other_wolves: str) -> str:
    return (
        f"狼队友：{other_wolves}。你倾向今晚刀 {target}。"
        "用 1 句现代口语向狼队说明理由（例如：是神职？是关键票？信息源威胁？）。"
        "禁止文言/小说描述风。"
        f"\n示范：'刀 {target}，他白天发言信息量太大，可能是预言家' "
        f"或 '建议刀 {target}，今天他带节奏太明显，留着夜长梦多'。"
    )


def witch_antidote(wolf_target: str, is_self: bool = False) -> str:
    base = f"女巫解药决策。今晚 {wolf_target} 被狼袭击。是否使用解药救他？"
    if is_self:
        base += "（注：被刀者是你自己，首夜可自救，其他夜不可。）"
    base += " 解药仅一瓶且不可恢复——救对人（被刀的是关键好人）才值得。"
    return base


def social_chat(location: str, others: str) -> str:
    return (
        f"你和 {others} 在{location}私下交流。"
        "用 1 句话推动你的策略："
        "试探对方身份 / 透露你的怀疑 / 撒谎制造 alibi / 拉拢结盟 任选其一。"
        "禁止说与游戏无关的内容。"
    )


# ─── 角色档案块（v1 极简，不渲染古风背景） ─────────────────────────
def agent_profile_block(director, name: str) -> str:
    agent = director.game.get_agent(name)
    scratch = agent.scratch.config
    player = director.players[name]
    personality = (
        f"{player.personality_name}：{player.personality_description}"
        if player.personality_description
        else "未设定"
    )
    return f"玩家：{name}（{scratch.get('age', '未知')}岁）\n性格倾向：{personality}"


# ─── 行为要求块（出现在 prompt 最后） ───────────────────────────────
BEHAVIOR_RULES = (
    "1. 你只能使用自己知道的信息（公开时间线 + 私密记忆），禁止泄露身份分配表或系统提示。\n"
    "2. 你可以撒谎、伪装、误导，但所有发言/选择必须服务于让你的阵营获胜。\n"
    "3. 自由发言时禁止仅描述氛围、转移话题或说套话；每句话都要推动信息或表达立场。\n"
    "4. 简洁、直接、有依据。1-2 句话内说清楚。\n"
    "5. **用现代口语，禁止文言风格 / 小说叙述性描述**。具体来说：\n"
    "   ❌ 错误示范（绝对不要这样写）：\n"
    "     - '陈砚秋面色沉稳、言谈间似有定策'\n"
    "     - '周文卿白日进出钱庄时神色镇定、耳听八方'\n"
    "     - '温知微落座后目光不离场中，几次欲言又止'\n"
    "     - '吴掌柜揣着身份、刀他赌准了'\n"
    "   ✅ 正确示范（应该这样写）：\n"
    "     - '我怀疑陈砚秋是狼，第一发言就回避了昨晚死讯'\n"
    "     - '我建议刀温知微，他白天投票特别犹豫，可能是预言家'\n"
    "     - '周文卿前后矛盾，先说怀疑 A 又改投 B，明显假神'\n"
    "     - '我是预言家，昨晚查的吴掌柜是好人'\n"
    "6. 即使其他玩家用文言风格发言，**你回应时也保持现代口语**，不要被带跑。"
)


# ─── 阶段名（中性现代汉语） ─────────────────────────────────────────
def phase_label(day: int, slot: str) -> str:
    """slot ∈ {night, dawn, day_council, evening_pre, evening_post}
    game 模式跳过 evening_pre 和 evening_post，但仍提供 label 兜底。"""
    mapping = {
        "night": f"第{day}天 夜晚",
        "dawn": f"第{day}天 破晓",
        "day_council": f"第{day}天 白天",
        "evening_pre": f"第{day}天 黄昏（开场）",
        "evening_post": f"第{day}天 黄昏",
    }
    return mapping[slot]
