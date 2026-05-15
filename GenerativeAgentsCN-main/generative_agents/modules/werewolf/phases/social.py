# 文件作用：申时（黄昏）自由活动——小组私聊、地点轮换、私密观察记忆。

from typing import List, Sequence, Tuple

from modules.werewolf.locations import SOCIAL_SPOTS
from modules.werewolf.llm_io import ask_text
from modules.werewolf.text_utils import join_names


def free_social_window(director, label: str, rounds: int = 2) -> None:
    alive = director.alive_names()
    if len(alive) < 2:
        return

    for round_idx in range(rounds):
        shuffled = alive[:]
        director.random.shuffle(shuffled)
        groups = _make_social_groups(director, shuffled)
        for idx, group in enumerate(groups):
            address = SOCIAL_SPOTS[(idx + round_idx) % len(SOCIAL_SPOTS)]
            director.move_many(group, address, f"在{label}进行非正式交谈", label, "闲聊")
            location = director.location_name(address)
            observation = f"{label}：你在{location}看见 {join_names(group)} 聚在一起交谈。"
            for name in group:
                director.private_log[name].append(observation)
                director.safe_remember(name, observation, node_type="event", poignancy=5)

            chats: List[Tuple[str, str]] = []
            for name in group:
                others = [n for n in group if n != name]
                speech = ask_text(
                    director,
                    name,
                    label,
                    (
                        f"你在{location}和 {join_names(others)} 非正式聊天。"
                        "请说一句自然的话，可以试探、交换看法、撒谎、安抚或暗示白天投票想法。"
                        "这不是公开议会，只有在场的人会记住。"
                    ),
                    fallback=_fallback_social_line(others),
                    max_chars=130,
                )
                chats.append((name, speech))
            director.record_dialogue(
                f"{group[0]} -> 私聊小组",
                address,
                chats,
                audience=group,
                public=False,
                phase=label,
            )
        director.save_checkpoint(f"{label}-第{round_idx + 1}轮私聊")


def _make_social_groups(director, names: Sequence[str]) -> List[List[str]]:
    """把一组人随机划分成 2-3 人的小组。"""
    groups: List[List[str]] = []
    idx = 0
    while idx < len(names):
        left = len(names) - idx
        if left == 1 and groups:
            groups[-1].append(names[idx])
            break
        size = 3 if left >= 3 and director.random.random() > 0.45 else 2
        groups.append(list(names[idx : idx + size]))
        idx += size
    return groups


def _fallback_social_line(others: Sequence[str]) -> str:
    target = join_names(others) or "你们"
    return f"{target}，等会儿广场上我想听更具体的票因，含糊带过的人我会重点看。"
