# 文件作用：子时（夜晚）阶段——狼队 / 守卫 / 预言家 / 女巫 / 猎人待命，以及破晓后的死亡结算 + NPC 流言。

from typing import Dict, List, Optional, Tuple

from modules.prompt import (
    GUARD_TASK,
    SEER_TASK,
    WEREWOLF_TARGET_TASK,
    WITCH_POISON_TASK,
    werewolf_speech_task,
    witch_antidote_task,
)
from modules.werewolf.locations import LOCATIONS, shichen
from modules.werewolf.llm_io import ask_choice, ask_text
from modules.werewolf.rules import resolve_night_deaths
from modules.werewolf.text_utils import join_names


def night_phase(director, day: int) -> None:
    phase = shichen(day, "子时")
    director.add_record("public", phase, f"夜幕降临。{phase}起，江南古镇万籁俱寂，秘密行动依次发生。")

    wolf_target = werewolf_action(director, phase)
    guard_target = guard_action(director, phase)
    seer_info = seer_action(director, phase)
    saved_by_witch, poison_target = witch_action(director, phase, wolf_target)
    hunter_wait_action(director, phase)

    deaths, narration = resolve_night_deaths(wolf_target, guard_target, saved_by_witch, poison_target)
    for line in narration:
        director.add_record("secret", phase, line)

    killed: List[str] = []
    for target, reasons in deaths.items():
        if director.players[target].alive:
            killed.append(target)
            director.kill_player(target, "、".join(reasons), phase)

    dawn = shichen(day + 1, "卯时")
    if killed:
        director.add_record(
            "public",
            dawn,
            f"{dawn}破晓，昨夜 {join_names(killed)} 殁于镇中。身份不翻，棺木抬归乱葬岗。",
        )
    else:
        director.add_record("public", dawn, f"{dawn}破晓，昨夜镇上风平浪静，是个平安夜。")

    if seer_info:
        seer_name, target, result = seer_info
        director.add_record(
            "secret", phase, f"{seer_name} 在观星楼夜观天象，问卜 {target}，所得 {result}。"
        )

    _spread_gossip(director, phase, day, dawn, wolf_target, guard_target, seer_info, saved_by_witch, poison_target)
    director.save_checkpoint(phase)


def _spread_gossip(
    director,
    phase: str,
    day: int,
    dawn: str,
    wolf_target: Optional[str],
    guard_target: Optional[str],
    seer_info,
    saved_by_witch: Optional[str],
    poison_target: Optional[str],
) -> None:
    """把昨夜真实事件用保守扭曲方式分发给清晨在场玩家。"""
    if not director.gossip_mill:
        return
    night_events = {
        "wolf_target": wolf_target,
        "saved_by_witch": saved_by_witch,
        "poison_target": poison_target,
        "witch_visited_clinic": (saved_by_witch is not None) or (poison_target is not None),
        "guard_active": guard_target is not None,
        "seer_active": seer_info is not None,
        "wolves_met": len(director.alive_names(role="werewolf")) > 0,
    }
    lines = director.gossip_mill.spin(night_events, day)
    audience = director.alive_names()
    for npc_name, line in lines:
        record = f"{npc_name}在镇上闲谈：{line}"
        director.add_record("public", dawn, record, location="镇中广场")
        for player_name in audience:
            director.private_log[player_name].append(f"{dawn} {record}")


def werewolf_action(director, phase: str) -> Optional[str]:
    wolves = director.alive_names(role="werewolf")
    candidates = [name for name in director.alive_names() if name not in wolves]
    if not wolves or not candidates:
        return None

    director.move_many(wolves, LOCATIONS["dyehouse"], "潜入后山染坊低声商量击杀目标", phase, "狼会")
    director.save_checkpoint(f"{phase}-狼队夜会")

    proposals: List[str] = []
    chats: List[Tuple[str, str]] = []
    for wolf in wolves:
        fallback_target = director.heuristic_target(wolf, candidates)
        target = ask_choice(
            director,
            wolf,
            phase,
            WEREWOLF_TARGET_TASK,
            candidates,
            fallback=fallback_target,
        )
        speech = ask_text(
            director,
            wolf,
            phase,
            werewolf_speech_task(target, join_names([w for w in wolves if w != wolf])),
            fallback=f"我建议今晚处理{target}，这个人白天的信息价值太高。",
            max_chars=120,
        )
        proposals.append(target)
        chats.append((wolf, speech))

    director.record_dialogue(
        f"{wolves[0]} -> 狼队",
        LOCATIONS["dyehouse"],
        chats,
        audience=wolves,
        public=False,
        phase=phase,
    )

    target = director.majority_choice(proposals)
    director.add_record("secret", phase, f"狼队最终决定击杀 {target}。")
    for wolf in wolves:
        director.private_log[wolf].append(f"{phase} 狼队目标：{target}")
    return target


def guard_action(director, phase: str) -> Optional[str]:
    guard = director.role_holder("guard", alive_only=True)
    if not guard:
        return None

    candidates = director.alive_names()
    if director.guard_last_target in candidates and len(candidates) > 1:
        candidates = [name for name in candidates if name != director.guard_last_target]
    director.move_agent(guard, LOCATIONS["watchman"], "从更夫房提灯出发，决定今晚守护谁", phase, 10, "守护")

    target = ask_choice(
        director,
        guard,
        phase,
        GUARD_TASK,
        candidates,
        fallback=director.heuristic_target(guard, candidates, prefer_self=True),
    )
    director.guard_last_target = target
    text = f"{phase}：你守护了 {target}。"
    director.private_log[guard].append(text)
    director.safe_remember(guard, text, node_type="thought", poignancy=8)
    director.add_record("secret", phase, f"守卫 {guard} 守护 {target}。")
    return target


def seer_action(director, phase: str) -> Optional[Tuple[str, str, str]]:
    seer = director.role_holder("seer", alive_only=True)
    if not seer:
        return None

    checked = director.seer_checks.setdefault(seer, {})
    candidates = [name for name in director.alive_names() if name != seer and name not in checked]
    if not candidates:
        return None

    director.move_agent(seer, LOCATIONS["stargazer"], "登观星楼夜观天象，问卜一名玩家的阵营", phase, 10, "查验")
    target = ask_choice(
        director,
        seer,
        phase,
        SEER_TASK,
        candidates,
        fallback=director.heuristic_target(seer, candidates),
    )
    result = "狼人" if director.players[target].role == "werewolf" else "好人"
    checked[target] = result
    text = f"{phase}：你查验了 {target}，结果是 {result}。"
    director.private_log[seer].append(text)
    director.safe_remember(seer, text, node_type="thought", poignancy=10)
    return seer, target, result


def witch_action(director, phase: str, wolf_target: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    witch = director.role_holder("witch", alive_only=True)
    if not witch:
        return None, None

    director.move_agent(witch, LOCATIONS["clinic"], "在同德医馆熬药，判断是否使用解药或毒药", phase, 10, "药剂")
    saved_by_witch: Optional[str] = None
    poison_target: Optional[str] = None
    used_potion_tonight = False  # 标准规则：一夜不能同用两药

    # 解药：标准规则下，女巫只能在首夜自救；其余夜可救他人。
    if director.witch_antidote and wolf_target:
        self_save_allowed = (wolf_target != witch) or (director.day == 1)
        if self_save_allowed:
            decision = ask_choice(
                director,
                witch,
                phase,
                witch_antidote_task(wolf_target, is_self=(wolf_target == witch)),
                ["救", "不救"],
                fallback="救",
            )
            if decision == "救":
                saved_by_witch = wolf_target
                director.witch_antidote = False
                used_potion_tonight = True
                text = f"{phase}：你使用解药救下了 {wolf_target}。"
                director.private_log[witch].append(text)
                director.safe_remember(witch, text, node_type="thought", poignancy=9)
        else:
            text = f"{phase}：你今晚被狼人袭击，但按规矩不能给自己用解药。"
            director.private_log[witch].append(text)
            director.safe_remember(witch, text, node_type="thought", poignancy=9)

    if director.witch_poison and not used_potion_tonight:
        candidates = ["不毒"] + [name for name in director.alive_names() if name != witch]
        decision = ask_choice(
            director,
            witch,
            phase,
            WITCH_POISON_TASK,
            candidates,
            fallback="不毒",
        )
        if decision != "不毒":
            poison_target = decision
            director.witch_poison = False
            text = f"{phase}：你使用毒药毒杀 {poison_target}。"
            director.private_log[witch].append(text)
            director.safe_remember(witch, text, node_type="thought", poignancy=9)

    director.add_record(
        "secret",
        phase,
        f"女巫行动：解药目标={saved_by_witch or '无'}，毒药目标={poison_target or '无'}。",
    )
    return saved_by_witch, poison_target


def hunter_wait_action(director, phase: str) -> None:
    hunter = director.role_holder("hunter", alive_only=True)
    if not hunter:
        return
    director.move_agent(hunter, LOCATIONS["inn"], "在归云客栈厢房擦拭家伙，等待临死反扑之机", phase, 10, "猎枪")
    director.private_log[hunter].append(f"{phase}：你仍然保留临死反扑的技能。")
