# 文件作用：斯坦福小镇狼人杀主入口，负责创建一局完整游戏并写出原始检查点。

import argparse
import json
import os
import sys
from datetime import datetime

from dotenv import find_dotenv, load_dotenv

from modules import utils


EXPECTED_PLAYER_COUNT = 12
GAME_START_TIME = "20240213-18:00"
REPLAY_STRIDE_MINUTES = 10
DEFAULT_PLAYERS = [
    "陈砚秋",
    "苏蘅",
    "林宛娘",
    "周文卿",
    "孟雨棠",
    "沈鹤年",
    "阿福",
    "温知微",
    "白潜舟",
    "徐慎之",
    "柳青禾",
    "吴掌柜",
]

# Kept for older helper scripts that imported start.personas.
personas = DEFAULT_PLAYERS


def parse_players(value):
    if not value:
        return DEFAULT_PLAYERS
    return [item.strip() for item in value.split(",") if item.strip()]


def load_role_map(path):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_players(players):
    if len(players) != EXPECTED_PLAYER_COUNT:
        raise ValueError("江南古镇狼人杀固定为12人局，请选择正好12名玩家。")

    duplicated = sorted({name for name in players if players.count(name) > 1})
    if duplicated:
        raise ValueError(f"玩家列表有重复姓名：{', '.join(duplicated)}")

    missing_assets = []
    for name in players:
        path = os.path.join(
            "frontend",
            "static",
            "assets",
            "village",
            "agents",
            name,
            "agent.json",
        )
        if not os.path.exists(path):
            missing_assets.append(name)
    if missing_assets:
        raise ValueError(f"找不到这些玩家的人设文件：{', '.join(missing_assets)}")


def default_game_name():
    return "werewolf-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="run one full 江南古镇 Werewolf game")
    parser.add_argument("--name", type=str, default="", help="game save name; auto-generated when omitted")
    parser.add_argument("--seed", type=int, default=None, help="random seed for role assignment and fallback choices")
    parser.add_argument("--players", type=str, default="", help="comma-separated 12 player names")
    parser.add_argument("--role-map", type=str, default="", help="optional JSON file mapping player name to role key")
    parser.add_argument("--verbose", type=str, default="info", help="debug|info|warn|error|critical")
    parser.add_argument("--log", type=str, default="", help="optional log file name under checkpoint folder")
    parser.add_argument("--no-llm", action="store_true", help="use deterministic fallbacks instead of calling the LLM API")
    parser.add_argument("--no-memory", action="store_true", help="do not write extra Werewolf memory nodes during this run")
    args = parser.parse_args()

    players = parse_players(args.players)
    validate_players(players)

    from modules.werewolf.director import WerewolfDirector, build_werewolf_config, load_agent_base

    game_name = args.name.strip() or default_game_name()
    checkpoints_folder = os.path.join("results", "checkpoints", game_name)
    if os.path.exists(checkpoints_folder):
        print(f"'{game_name}' already exists. Please choose a new --name.")
        return 1
    os.makedirs(checkpoints_folder, exist_ok=True)

    if args.log:
        logger = utils.create_file_logger(os.path.join(checkpoints_folder, args.log), args.verbose)
    else:
        logger = utils.create_io_logger(args.verbose)

    config = build_werewolf_config(
        GAME_START_TIME,
        REPLAY_STRIDE_MINUTES,
        players,
        load_agent_base(),
    )
    if args.no_memory:
        config["agent_base"]["associate"] = {"disabled": True}

    director = WerewolfDirector(
        game_name,
        "frontend/static",
        checkpoints_folder,
        config,
        seed=args.seed,
        role_map=load_role_map(args.role_map),
        use_llm=not args.no_llm,
        write_memory=not args.no_memory,
        logger=logger,
    )
    state = director.run()

    print("\n江南古镇狼人杀模拟完成。")
    print(f"本局名称：{game_name}")
    print(f"胜利阵营：{state.get('winner') or '未决'}")
    print(f"检查点目录：{checkpoints_folder}")
    print(f"狼人杀报告：{os.path.join(checkpoints_folder, 'werewolf_report.md')}")
    print(f"生成回放数据：python compress.py --name {game_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
