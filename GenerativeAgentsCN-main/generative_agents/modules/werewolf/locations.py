# 文件作用：江南古镇场景的地点常量与显示名映射。纯数据，无依赖。
# 注意：LOCATIONS 的 address 必须与 frontend/static/assets/village/maze.json 中的 tile 地址对齐。

from typing import Dict, List


# Maze tile 地址（4 级：world / sector / arena / game_object）。
# 引擎按该地址定位瓦片，并把角色 move 到该 tile。
LOCATIONS: Dict[str, List[str]] = {
    "square": ["the Ville", "镇中广场", "广场前", "议事台"],
    "teahouse": ["the Ville", "听雨茶馆", "大堂", "雅间茶桌"],
    "clinic": ["the Ville", "镇东药市", "铺面", "药柜后"],
    "stargazer": ["the Ville", "观星楼", "观星阁"],
    "watchman": ["the Ville", "更夫房院", "钟楼底", "更夫椅"],
    "dyehouse": ["the Ville", "后山染坊", "染缸房", "染料库"],
    "nightmarket": ["the Ville", "镇东药市", "铺面", "杂货柜"],
    "inn": ["the Ville", "归云客栈", "客栈大堂", "客栈板凳"],
    "graveyard": ["the Ville", "镇中广场", "广场前"],
}

# Prompt 与日志中向 Agent / 玩家展示的地点名（江南叙事层）。
LOCATION_DISPLAY: Dict[str, str] = {
    "square": "镇中广场",
    "teahouse": "听雨茶馆",
    "clinic": "同德医馆",
    "stargazer": "观星楼",
    "watchman": "更夫房",
    "dyehouse": "后山染坊",
    "nightmarket": "码头夜市",
    "inn": "归云客栈",
    "graveyard": "镇外乱葬岗",
}

# 神职夜晚强制移动的专属地点 key。
ROLE_LOCATIONS: Dict[str, str] = {
    "werewolf": "dyehouse",
    "seer": "stargazer",
    "witch": "clinic",
    "guard": "watchman",
    "hunter": "inn",
}

# 黄昏自由活动可去的地点。
SOCIAL_SPOT_KEYS: List[str] = ["teahouse", "nightmarket", "square", "inn"]
SOCIAL_SPOTS: List[List[str]] = [LOCATIONS[k] for k in SOCIAL_SPOT_KEYS]


def shichen(day: int, slot: str) -> str:
    """按时辰格式化阶段标签，例：shichen(1, '子时') -> '第1日子时'。"""
    return f"第{day}日{slot}"


def location_display_from_address(address):
    """根据 maze 地址反查显示名；未匹配时回退到原地址末段。"""
    addr = list(address)
    for key, bound in LOCATIONS.items():
        if addr == bound:
            return LOCATION_DISPLAY[key]
    return "，".join(address[1:]) if len(address) > 1 else address[0]
