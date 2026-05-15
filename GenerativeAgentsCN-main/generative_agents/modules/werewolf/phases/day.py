# 文件作用：辰时议会（白天）——集合发言、辩论质疑、投票放逐。

from typing import Dict, List, Sequence, Tuple

from modules.prompt import (
    DAY_SPEECH_TASK,
    DEBATE_TARGET_TASK,
    TIE_DEFENSE_TASK,
    debate_answer_task,
    debate_question_task,
    vote_task,
)
from modules.werewolf.locations import LOCATIONS, shichen
from modules.werewolf.llm_io import ask_choice, ask_text
from modules.werewolf.player import fallback_speech
from modules.werewolf.rules import resolve_vote, tied_candidates
from modules.werewolf.text_utils import join_names


def day_phase(director, day: int) -> None:
    phase = shichen(day, "辰时议会")
    alive = director.alive_names()
    director.move_many(alive, LOCATIONS["square"], "在镇中广场牌坊下集合参加白日议会", phase, "议会")
    director.add_record(
        "public", phase, f"所有幸存者在镇中广场集合。发言顺序：{join_names(alive)}。"
    )
    director.save_checkpoint(f"{phase}-集合")

    speeches: List[Tuple[str, str]] = []
    for name in alive:
        speech = ask_text(
            director,
            name,
            phase,
            DAY_SPEECH_TASK,
            fallback=fallback_speech(director.players[name].role),
            max_chars=180,
        )
        speeches.append((name, speech))
        director.record_trajectory(
            agent=name, phase=phase, decision_type="speech",
            action=speech,
            extra_obs={"speech_kind": "议会顺序发言"},
        )

    director.record_dialogue(
        f"{alive[0]} -> 全体",
        LOCATIONS["square"],
        speeches,
        audience=alive,
        public=True,
        phase=phase,
    )
    director.save_checkpoint(f"{phase}-顺序发言")

    debate_phase(director, phase)
    vote_phase(director, phase)
    director.save_checkpoint(f"{phase}-投票结算")


def debate_phase(director, phase: str) -> None:
    alive = director.alive_names()
    if len(alive) <= 3:
        return

    challengers = alive[:]
    director.random.shuffle(challengers)
    challengers = challengers[: min(director.debate_turns, len(challengers))]
    chats: List[Tuple[str, str]] = []
    for challenger in challengers:
        candidates = [name for name in alive if name != challenger]
        target = ask_choice(
            director,
            challenger,
            phase,
            DEBATE_TARGET_TASK,
            candidates,
            fallback=director.heuristic_target(challenger, candidates),
        )
        question = ask_text(
            director,
            challenger,
            phase,
            debate_question_task(target),
            fallback=f"{target}，你刚才的发言回避了关键死亡信息，我想听你解释为什么。",
            max_chars=120,
        )
        answer = ask_text(
            director,
            target,
            phase,
            debate_answer_task(challenger),
            fallback="我理解你的怀疑，但我刚才是在整理信息，不是在回避问题。",
            max_chars=120,
        )
        chats.extend([(challenger, question), (target, answer)])

    director.record_dialogue(
        f"{chats[0][0]} -> 辩论席",
        LOCATIONS["square"],
        chats,
        audience=alive,
        public=True,
        phase=phase,
    )
    director.save_checkpoint(f"{phase}-辩论")


def vote_phase(director, phase: str) -> None:
    alive = director.alive_names()
    votes = collect_votes(director, phase, alive, alive)
    exile = resolve_vote(votes)

    if exile is None:
        tied = tied_candidates(votes)
        if len(tied) > 1:
            director.add_record(
                "public", phase, f"首轮投票平票：{join_names(tied)}。平票之人当众辩解。"
            )
            defenses: List[Tuple[str, str]] = []
            for name in tied:
                defense = ask_text(
                    director,
                    name,
                    phase,
                    TIE_DEFENSE_TASK,
                    fallback="我认为现在票我太急了，至少再听一轮信息会更稳。",
                    max_chars=120,
                )
                defenses.append((name, defense))
            director.record_dialogue(
                f"{tied[0]} -> 全体",
                LOCATIONS["square"],
                defenses,
                audience=alive,
                public=True,
                phase=phase,
            )
            # 标准规则：平票辩解后，二轮可投全场存活，不限于首轮平票人
            revotes = collect_votes(director, phase, alive, alive, revote=True)
            exile = resolve_vote(revotes)

    if exile:
        director.add_record("public", phase, f"议会决议：{exile} 被放逐出镇。")
        director.kill_player(exile, "白天放逐", phase)
    else:
        director.add_record("public", phase, "议会僵持，本轮无人被放逐。")


def collect_votes(
    director,
    phase: str,
    voters: Sequence[str],
    candidates_pool: Sequence[str],
    *,
    revote: bool = False,
) -> Dict[str, str]:
    votes: Dict[str, str] = {}
    for voter in voters:
        candidates = [
            name
            for name in candidates_pool
            if name != voter and director.players[name].alive
        ]
        if not candidates:
            continue
        target = ask_choice(
            director,
            voter,
            phase,
            vote_task(revote=revote),
            candidates,
            fallback=director.heuristic_target(voter, candidates),
        )
        votes[voter] = target
        director.record_trajectory(
            agent=voter, phase=phase, decision_type="vote",
            action=target, candidates=candidates,
            extra_obs={"vote_round": "revote" if revote else "first"},
        )

    vote_text = "；".join(f"{voter}->{target}" for voter, target in votes.items())
    director.add_record(
        "public", phase, f"{'第二轮' if revote else '首轮'}投票：{vote_text}"
    )
    return votes
