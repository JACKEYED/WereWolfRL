# 文件作用：辰时议会（白天）——集合发言、辩论质疑、投票放逐。

from typing import Dict, List, Sequence, Tuple

from modules.werewolf.locations import LOCATIONS
from modules.werewolf.llm_io import ask_choice, ask_text
from modules.werewolf.player import fallback_speech
from modules.werewolf.rules import resolve_vote, tied_candidates
from modules.werewolf.text_utils import join_names


def day_phase(director, day: int) -> None:
    phase = director.phase_label(day, "day_council")
    alive = director.alive_names()
    gather_desc = (
        "前往广场集合参加白天议会"
        if director.scene_mode == "game"
        else "在镇中广场牌坊下集合参加白日议会"
    )
    director.move_many(alive, LOCATIONS["square"], gather_desc, phase, "议会")
    gather_msg = (
        f"全部幸存玩家集合于广场。发言顺序：{join_names(alive)}。"
        if director.scene_mode == "game"
        else f"所有幸存者在镇中广场集合。发言顺序：{join_names(alive)}。"
    )
    director.add_record("public", phase, gather_msg)
    director.save_checkpoint(f"{phase}-集合")

    speeches: List[Tuple[str, str]] = []
    for name in alive:
        speech = ask_text(
            director,
            name,
            phase,
            director.task("day_speech"),
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
            director.task("debate_target"),
            candidates,
            fallback=director.heuristic_target(challenger, candidates),
        )
        director.record_trajectory(
            agent=challenger, phase=phase, decision_type="choice",
            action=target, candidates=candidates,
            extra_obs={"choice_kind": "debate_target"},
        )
        question = ask_text(
            director,
            challenger,
            phase,
            director.task("debate_question", target=target),
            fallback=f"{target}，你刚才的发言回避了关键死亡信息，我想听你解释为什么。",
            max_chars=120,
        )
        director.record_trajectory(
            agent=challenger, phase=phase, decision_type="speech",
            action=question,
            extra_obs={"speech_kind": "debate_question", "target": target},
        )
        answer = ask_text(
            director,
            target,
            phase,
            director.task("debate_answer", challenger=challenger),
            fallback="我理解你的怀疑，但我刚才是在整理信息，不是在回避问题。",
            max_chars=120,
        )
        director.record_trajectory(
            agent=target, phase=phase, decision_type="speech",
            action=answer,
            extra_obs={"speech_kind": "debate_answer", "challenger": challenger},
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
            tie_msg = (
                f"首轮投票平票：{join_names(tied)}。平票玩家各做 1-2 句辩解。"
                if director.scene_mode == "game"
                else f"首轮投票平票：{join_names(tied)}。平票之人当众辩解。"
            )
            director.add_record("public", phase, tie_msg)
            defenses: List[Tuple[str, str]] = []
            for name in tied:
                defense = ask_text(
                    director,
                    name,
                    phase,
                    director.task("tie_defense"),
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
        msg = (
            f"投票结果：{exile} 被放逐出局。"
            if director.scene_mode == "game"
            else f"议会决议：{exile} 被放逐出镇。"
        )
        director.add_record("public", phase, msg)
        director.kill_player(exile, "白天放逐", phase)
    else:
        msg = (
            "投票未形成多数，本轮无人出局。"
            if director.scene_mode == "game"
            else "议会僵持，本轮无人被放逐。"
        )
        director.add_record("public", phase, msg)


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
            director.task("vote", revote=revote),
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
