# 文件作用：日志/对话/检查点/报告的记录与序列化。
# 所有函数以 director 为首参数；在 director.py 里把它们绑成 WerewolfDirector 的方法。

import json
import os
from dataclasses import asdict
from typing import List, Optional, Sequence, Tuple

from modules import memory, utils


def add_record(
    director,
    scope: str,
    phase: str,
    text: str,
    *,
    actors: Optional[Sequence[str]] = None,
    location: Optional[str] = None,
) -> None:
    """追加一条事件记录到 phase_records；scope=public 时同步进 public_log。"""
    stamp = utils.get_timer().get_date("%Y%m%d-%H:%M")
    entry = {
        "time": stamp,
        "day": director.day,
        "phase": phase,
        "scope": scope,
        "text": text,
        "actors": list(actors or []),
        "location": location or "",
    }
    director.phase_records.append(entry)
    if scope == "public":
        director.public_log.append(f"{stamp} {text}")
    director.logger.info(f"[{scope}] {phase}: {text}")


def record_dialogue(
    director,
    title: str,
    address: Sequence[str],
    chats: Sequence[Tuple[str, str]],
    *,
    audience: Sequence[str],
    public: bool,
    phase: str,
) -> None:
    """把一组对话写入 conversation、phase_records、对应受众的 private_log/向量记忆。"""
    key = utils.get_timer().get_date("%Y%m%d-%H:%M")
    director.game.conversation.setdefault(key, [])
    director.game.conversation[key].append({f"{title} @ {':'.join(address)}": list(chats)})

    location = director.location_name(address)
    for speaker, text in chats:
        clean = director.clean_text(text, 220)
        if public:
            record = f"{speaker} 在{location}公开发言：{clean}"
            add_record(director, "public", phase, record, actors=[speaker], location=location)
            safe_broadcast(director, record, phase)
        else:
            record = f"{speaker} 在{location}私下说：{clean}"
            add_record(director, "social", phase, record, actors=[speaker], location=location)
            for name in audience:
                director.private_log[name].append(record)
                safe_remember(director, name, record, node_type="chat", poignancy=6)


def safe_broadcast(director, text: str, phase: str) -> None:
    for name in director.alive_names():
        safe_remember(director, name, f"{phase}：{text}", node_type="event", poignancy=7)


def safe_remember(director, name: str, text: str, *, node_type: str, poignancy: int) -> None:
    if not director.write_memory:
        return
    try:
        agent = director.game.get_agent(name)
        address = agent.get_tile().get_address() if agent.coord else ["the Ville"]
        event = memory.Event(
            name,
            "记住",
            "狼人杀线索",
            describe=text,
            address=address,
            emoji="记忆",
        )
        agent.associate.add_node(node_type, event, poignancy=poignancy)
    except Exception as exc:
        director.logger.warning(f"{name} 写入狼人杀记忆失败：{exc}")


def state_dict(director, phase: str) -> dict:
    """导出当前完整游戏状态，用于检查点和 API 响应。"""
    return {
        "name": director.name,
        "phase": phase,
        "day": director.day,
        "winner": director.winner,
        "players": {name: asdict(player) for name, player in director.players.items()},
        "role_names": {name: player.role_name for name, player in director.players.items()},
        "alive": director.alive_names(),
        "witch": {
            "antidote": director.witch_antidote,
            "poison": director.witch_poison,
        },
        "guard_last_target": director.guard_last_target,
        "seer_checks": director.seer_checks,
        "public_log": director.public_log,
        "private_log": director.private_log,
        "phase_records": director.phase_records,
    }


def save_checkpoint(director, phase: str) -> None:
    """把当前 game state 写到磁盘检查点，并推进模拟时间。"""
    director.step += 1
    sim_time = utils.get_timer().get_date("%Y%m%d-%H:%M")
    for name, agent in director.game.agents.items():
        director.config["agents"].setdefault(name, {})
        director.config["agents"][name].update(agent.to_dict())
        director.config["agents"][name]["coord"] = list(agent.coord)

    director.config.update(
        {
            "time": sim_time,
            "step": director.step,
            "werewolf": state_dict(director, phase),
        }
    )
    checkpoint = os.path.join(
        director.checkpoints_folder, f"simulate-{sim_time.replace(':', '')}.json"
    )
    with open(checkpoint, "w", encoding="utf-8") as f:
        f.write(json.dumps(director.config, indent=2, ensure_ascii=False))
    with open(director.conversation_log, "w", encoding="utf-8") as f:
        f.write(json.dumps(director.game.conversation, indent=2, ensure_ascii=False))
    with open(
        os.path.join(director.checkpoints_folder, "werewolf_state.json"), "w", encoding="utf-8"
    ) as f:
        f.write(json.dumps(state_dict(director, phase), indent=2, ensure_ascii=False))

    stride = int(director.config.get("stride", 10))
    if stride > 0:
        utils.get_timer().forward(stride)


def write_report(director) -> None:
    """局末写一份 Markdown 复盘报告。"""
    lines: List[str] = [
        "# 狼人杀社会模拟报告",
        "",
        f"模拟名称：{director.name}",
        f"胜利阵营：{director.winner or '未决'}",
        "",
        "## 身份表",
        "",
    ]
    for name in director.players_order:
        player = director.players[name]
        status = "存活" if player.alive else f"死亡：{player.death_reason}"
        lines.append(f"- {name}：{player.role_name}，{status}")
    lines.extend(["", "## 时间线", ""])
    for record in director.phase_records:
        prefix = "公开" if record["scope"] == "public" else record["scope"]
        lines.append(f"- `{record['time']}` [{prefix}] {record['phase']}：{record['text']}")
    lines.extend(["", "## 私密记忆摘要", ""])
    for name in director.players_order:
        lines.append(f"### {name}")
        for item in director.private_log.get(name, [])[-20:]:
            lines.append(f"- {item}")
        lines.append("")

    path = os.path.join(director.checkpoints_folder, "werewolf_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
